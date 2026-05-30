import random
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
from tqdm import tqdm

from wqbkit.app.core.alpha_db_core import AlphaDbCore
from wqbkit.app.database.schemas import TaskData, FactorData
from wqbkit.modules.regular_alpha.alpha_machine.alpha_generator import AlphaGenerator


class AlphaMachine(AlphaDbCore):
    CORRELATION_THRESHOLD = 0.85
    MAX_SELECTED = 100
    MIN_DRAWDOWN = 1
    SHARPE_THRESHOLD = 0.5
    TWO_YEAR_SHARPE_THRESHOLD = 0.5
    FALLBACK_SHARPE_THRESHOLD = 0.3
    FALLBACK_TWO_YEAR_SHARPE_THRESHOLD = 0.3
    MAX_GENERATED = 15000

    def __init__(self) -> None:
        super().__init__()
        self.operators: List[str] = []
        self.all_operators: List[str] = []
        self.get_operator()
        self.generator = AlphaGenerator()

    def get_operator(self) -> None:
        resp = self.wqbs.search_operators()
        self.operators = [item['name'] for item in resp.json() if 'REGULAR' in item['scope']]
        self.all_operators = [item['name'] for item in resp.json()]

    def _update_metadata(
        self,
        alpha_id: str,
        data_fields_all: Set[str],
        operators_all: Set[str],
    ) -> List[str]:
        expr = self.dbmanager.alphasimulated_get_by_alpha_id(alpha_id).expression
        operators_used, data_fields_used = self.extract_tokens(expr)
        data_fields_all.update(data_fields_used)
        operators_all.update(operators_used)
        return data_fields_used

    def _filter_by_correlation(
        self,
        alpha_ids: List[str],
        threshold: float,
        max_num: int,
    ) -> Tuple[List[str], List[str], Set[str], Set[str], pd.DataFrame]:
        self.logger.info(f'默认选中 {alpha_ids[0]}')
        selected = [alpha_ids[0]]
        dont_select = []
        alpha_returns = self.get_alpha_results(alpha_ids[0])
        
        data_fields_all: Set[str] = set()
        operators_all: Set[str] = set()
        
        self._update_metadata(alpha_ids[0], data_fields_all, operators_all)
        
        n = len(alpha_ids)
        with tqdm(total=n-1, desc=f"根据{threshold:.2f}相关性选取因子", mininterval=0.1) as pbar:
            for i in range(1, n):
                alpha_id = alpha_ids[i]
                returns = self.get_alpha_results(alpha_id)
                
                alpha_returns_tmp = pd.concat([alpha_returns, returns], axis=1)
                correlations = alpha_returns_tmp[selected].corrwith(alpha_returns_tmp[alpha_id])
                max_corr = correlations.max()
                
                if max_corr <= threshold:
                    status = "已选中"
                    selected.append(alpha_id)
                    alpha_returns = alpha_returns_tmp
                    self._update_metadata(alpha_id, data_fields_all, operators_all)
                    if len(selected) % 5 == 0 and threshold > 0.7:
                        threshold = threshold - 0.05
                        pbar.set_description(f"根据{threshold:.2f}相关性选取因子")
                else:
                    status = "未选中"
                    dont_select.append(alpha_id)
                
                pbar.set_postfix(
                    alpha_id=alpha_id,
                    max_corr=f"{max_corr:.4f}",
                    status=status,
                    selected=f"{len(selected)}/{max_num}",
                )
                pbar.update(1)
                
                if len(selected) >= max_num:
                    break
        return selected, dont_select, data_fields_all, operators_all, alpha_returns

    def _filter_by_diversity(
        self,
        dont_select: List[str],
        selected: List[str],
        max_num: int,
        data_fields_all: Set[str],
        operators_all: Set[str],
        alpha_returns: pd.DataFrame,
    ) -> List[str]:
        if len(selected) >= max_num or not dont_select:
            return selected

        corr_map: Dict[str, float] = {}
        for alpha_id in dont_select:
            returns = self.get_alpha_results(alpha_id)
            alpha_returns_tmp = pd.concat([alpha_returns, returns], axis=1)
            correlations = alpha_returns_tmp[selected].corrwith(alpha_returns_tmp[alpha_id])
            corr_map[alpha_id] = correlations.max()
        
        dont_select.sort(key=lambda x: corr_map.get(x, 1.0))
        
        n_rejected = len(dont_select)
        with tqdm(total=n_rejected, desc="根据表达式选取因子", mininterval=0.1) as pbar:
            for i in range(n_rejected):
                if len(selected) >= max_num:
                    break
                    
                alpha_id = dont_select[i]
                expr = self.dbmanager.alphasimulated_get_by_alpha_id(alpha_id).expression
                operators_used, data_fields_used = self.extract_tokens(expr)
                
                data_field_check = any(field not in data_fields_all for field in data_fields_used)

                if data_field_check:
                    status = "已选中"
                    selected.append(alpha_id)
                    data_fields_all.update(data_fields_used)
                    operators_all.update(operators_used)
                else:
                    status = "未选中"
                
                pbar.set_postfix(
                    alpha_id=alpha_id,
                    status=status,
                    selected=f"{len(selected)}/{max_num}",
                )
                pbar.update(1)
        return selected

    def filter_low_correlation_alphas(
        self,
        alpha_ids: List[str],
        threshold: float = CORRELATION_THRESHOLD,
        max_num: int = MAX_SELECTED,
    ) -> List[str]:
        if len(alpha_ids) == 0:
            return []
        self.logger.info(f"开始处理{len(alpha_ids)}个alpha...")

        # First pass: Correlation
        selected, dont_select, data_fields_all, operators_all, alpha_returns = self._filter_by_correlation(alpha_ids, threshold, max_num)
        
        # Second pass: Diversity
        # selected = self._filter_by_diversity(dont_select, selected, max_num, data_fields_all, operators_all, alpha_returns)

        self.logger.info(f"筛选完成！原始数量：{len(alpha_ids)}，保留数量：{len(selected)}，剔除数量：{len(alpha_ids)-len(selected)}")
        self.logger.info(f"保留的低相关性alpha列表：{selected}")

        return selected

    def prune_corration(self, task_id: int, pnl_clear: bool) -> List[str]:
        # 获取 alpha 数据
        alpha_data = self.dbmanager.alphasimulated_get_by_task_id(task_id)

        # 获取 alpha_id
        alpha_info = [
            a
            for a in tqdm(alpha_data, desc='根据表现筛选alpha', mininterval=0.1)
            if a.sharpe >= self.SHARPE_THRESHOLD
        ]

        self.logger.info(f'根据表现筛选alpha后剩余 {len(alpha_info)} 个alpha')

        seen = set()
        alpha_info_final = []
        for item in tqdm(alpha_info, desc='根据表达式去重', mininterval=0.1):
            expr = item.expression
            if expr not in seen:
                seen.add(expr)
                alpha_info_final.append(item)
        
        self.logger.info(f"根据表达式去重后剩余 {len(alpha_info_final)} 个alpha")

        alpha_info = alpha_info_final
        # 根据sharpe从高到低
        self.logger.info('根据sharpe从高到低:')
        alpha_info.sort(key=lambda x: x.sharpe, reverse=True)
        selected_alphas1 = self.filter_low_correlation_alphas(
            [alpha.alpha_id for alpha in alpha_info],
            threshold=self.CORRELATION_THRESHOLD,
        )

        # 根据fitness从高到低
        self.logger.info('根据fitness从高到低:')
        alpha_info.sort(key=lambda x: x.fitness, reverse=True)
        selected_alphas2 = self.filter_low_correlation_alphas(
            [alpha.alpha_id for alpha in alpha_info],
            threshold=self.CORRELATION_THRESHOLD,
        )

        # 根据two_year_sharpe从高到低
        self.logger.info('根据two_year_sharpe从高到低:')
        alpha_info.sort(key=lambda x: x.twoyearsharpe, reverse=True)
        selected_alphas3 = self.filter_low_correlation_alphas(
            [alpha.alpha_id for alpha in alpha_info],
            threshold=self.CORRELATION_THRESHOLD,
        )

        # 根据operator count从低到高
        self.logger.info('根据operator count从低到高:')
        alpha_info.sort(key=lambda x: len(self.extract_tokens(x.expression)[1]))
        selected_alphas4 = self.filter_low_correlation_alphas(
            [alpha.alpha_id for alpha in alpha_info],
            threshold=self.CORRELATION_THRESHOLD,
        )

        if pnl_clear:
            self.dbmanager.alphapnl_delete([alpha.alpha_id for alpha in alpha_info])

        return list(set(selected_alphas1 + selected_alphas2 + selected_alphas3 + selected_alphas4))

    def _submit_generated_alphas(
        self,
        name,
        parent_task_id: int,
        generation: int,
        expression_list: List[str],
        priority: int,
        pre: str,
        region: str,
        universe: str,
        neutralization: str,
        decay: int,
        tag: Optional[str],
    ) -> None:
        if not expression_list:
            return

        random.shuffle(expression_list)
        self.logger.info(f"生成 {len(expression_list)} 个{generation}阶alpha, 取{min(self.MAX_GENERATED, len(expression_list))}")
        expression_list = expression_list[: self.MAX_GENERATED]

        new_task_id = self.dbmanager.alphatask_insert(TaskData(
            pre=pre,
            name=name,
            region=region,
            universe=universe,
            neutralization=neutralization,
            decay=decay,
            generation=generation,
            priority=priority,
            parent_task_id=parent_task_id,
            total_alphas=len(expression_list),
            tag=tag,
        ))
        
        factor_list = []
        for expression in tqdm(expression_list, desc=f'{generation}阶表达式插入'):
            factor_data = FactorData(
                factor_id=None,
                pre=pre,
                expression=expression,
                region=region,
                universe=universe,
                neutralization=neutralization,
                decay=decay,
                priority=priority,
                task_id=new_task_id,
                generation=generation,
                tag=tag
            )
            factor_list.append(factor_data)
        self.dbmanager.alphafactor_bulk_insert(factor_list)

    def machine(
        self,
        task_id: Optional[int] = None,
        atom: bool = False,
        fundamental: bool = False,
        pv: bool = False,
        pnl_clear: bool = False,
        priority: Optional[int] = None,
    ) -> bool:
        if task_id:
            task_data = self.dbmanager.alphatask_get_by_id(task_id)
        else:
            task_data = self.dbmanager.alphatask_get_finished()
        if task_data is None:
            self.logger.info("没有已完成模拟的任务，等待下一次检查")
            return False

        task_id = task_data.task_id
        name = task_data.name
        generation = task_data.generation
        pre = task_data.pre
        region = task_data.region
        neutralization = task_data.neutralization
        universe = task_data.universe
        decay = task_data.decay
        tag = task_data.tag
        self.logger.info(f"找到一批alpha, task_id为 {task_id}")
        # 剪枝
        selected_alphas = self.prune_corration(task_id, pnl_clear)

        # 获取剪枝后的alpha数据
        expressions = [self.dbmanager.alphasimulated_get_by_alpha_id(alpha_id).expression for alpha_id in selected_alphas]

        self.logger.info(f"现在是第 {generation} 代，母数据有 {len(expressions)}个")

        # 根据减枝后的alpha生成下一阶段的alpha，注意分阶段
        if generation == -1 and len(expressions) > 0:
            expression_list = []
            for expression in tqdm(expressions, desc='生成零阶表达式'):
                expression_list.extend(self.generator.zero_order_factory(expression))
            
            self._submit_generated_alphas(name, task_id, 0, expression_list, priority or 0, pre, region, universe, neutralization, decay, tag)

        if generation == 0 and len(expressions) > 0:
            # 原始alpha用first_order_factory生成一阶alpha
            expression_list = []
            for expression in tqdm(expressions, desc='生成ts表达式'):
                expression_list.extend(self.generator.first_order_factory(expression))
            
            self._submit_generated_alphas(name, task_id, 1, expression_list, priority or 1, pre, region, universe, neutralization, decay, tag)

            expression_list = []
            for expression in tqdm(expressions, desc='生成group表达式'):
                expression_list.extend(self.generator.second_order_factory(expression, region, atom, fundamental, pv))

            self._submit_generated_alphas(name, task_id, 2, expression_list, priority or 2, pre, region, universe, neutralization, decay, tag)

        if generation == 1 and len(expressions) > 0:
            # 一阶alpha用second_order_factory生成二阶alpha
            expression_list = []
            for expression in tqdm(expressions, desc='生成group表达式'):
                expression_list.extend(self.generator.second_order_factory(expression, region, atom, fundamental, pv))
            
            self._submit_generated_alphas(name, task_id, 2, expression_list, priority or 2, pre, region, universe, neutralization, decay, tag)

        self.dbmanager.alphatask_mark_as_generated(task_id)
        if generation == 3:
            # 三阶alpha不用生成新的alpha, 从已有因子中提取效果不错的因子
            pass
        return True
