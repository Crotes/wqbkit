from concurrent.futures import ThreadPoolExecutor
import json
from typing import List, Tuple

import pandas as pd
import re

from wqbkit.app.core.alpha_base_core import AlphaBaseCore
from wqbkit.app.core.wqb_urls import URL_ALPHA_PNL
from wqbkit.app.database.alpha_db_manager import AlphaDBManager

MAX_WORKERS: int = 10
RETENTION_YEARS: int = 4


class AlphaDbCore(AlphaBaseCore):
    """Alpha PnL 数据访问与转换。"""

    def __init__(self) -> None:
        super().__init__()
        self.dbmanager = AlphaDBManager()
        self.retention_years = RETENTION_YEARS
        self.get_operators()

    def _get_alpha_pnl(self, alpha_id: str) -> pd.DataFrame:
        """获取单个 Alpha 的 PnL 数据。"""
        pnl_cache = self.dbmanager.alphapnl_get(alpha_id)

        if pnl_cache:
            pnl_data = json.loads(pnl_cache)
        else:
            try:
                url = URL_ALPHA_PNL.format(alpha_id)
                response = self.get(url)
            except Exception as e:
                print(url)
                self.logger.error(f"Error fetching PnL for {alpha_id}: {e}")
                return pd.DataFrame()

            pnl_data = response.json()
            self.dbmanager.alphapnl_upsert(alpha_id, json.dumps(pnl_data))

        try:
            df = pd.DataFrame(
                pnl_data["records"],
                columns=[item["name"] for item in pnl_data["schema"]["properties"]],
            )
            df = df.rename(columns={"date": "Date", "pnl": alpha_id})
            df["Date"] = pd.to_datetime(df["Date"])
            return df[["Date", alpha_id]].set_index("Date")
        except Exception as e:
            self.logger.error(f"Error processing PnL data for {alpha_id}: {e}")
            return pd.DataFrame()

    def get_alpha_pnls(self, alpha_ids: List[str]) -> pd.DataFrame:
        """获取多个 Alpha 的 PnL 数据。
        
        优化策略:
        1. 批量查询数据库缓存
        2. 仅对未缓存的 alpha_id 发起并发 API 请求
        3. 批量更新缓存
        4. 统一处理数据
        """
        if not alpha_ids:
            return pd.DataFrame()
            
        # 1. 批量查询缓存
        try:
            cached_pnls = self.dbmanager.alphapnl_bulk_get(alpha_ids)
        except Exception as e:
            self.logger.error(f"Error bulk getting PnL: {e}")
            cached_pnls = {}
        
        # 找出未命中的 alpha_ids
        missing_ids = [aid for aid in alpha_ids if aid not in cached_pnls]
        
        # 2. 并发获取缺失的数据
        new_pnls = {}
        if missing_ids:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # 定义单个获取任务
                def fetch_pnl(alpha_id):
                    try:
                        url = URL_ALPHA_PNL.format(alpha_id)
                        response = self.get(url)
                        data = response.json()
                        return alpha_id, json.dumps(data)
                    except Exception as e:
                        self.logger.error(f"Error fetching PnL for {alpha_id}: {e}")
                        return alpha_id, None

                # 执行并发请求
                results = executor.map(fetch_pnl, missing_ids)
                
                # 收集结果
                for item in results:
                    if item:
                        alpha_id, pnl_json = item
                        if pnl_json:
                            new_pnls[alpha_id] = pnl_json
                        
            # 3. 批量更新缓存
            if new_pnls:
                try:
                    self.dbmanager.alphapnl_bulk_upsert(new_pnls)
                except Exception as e:
                    self.logger.error(f"Error bulk upserting PnL: {e}")
        
        # 合并所有数据源
        all_pnl_data = {**cached_pnls, **new_pnls}
        
        # 4. 统一转换为 DataFrame
        dfs = []
        for alpha_id in alpha_ids: # 保持原有顺序
            pnl_json = all_pnl_data.get(alpha_id)
            if not pnl_json:
                continue
                
            try:
                pnl_data = json.loads(pnl_json)
                if not pnl_data or "records" not in pnl_data or "schema" not in pnl_data:
                    continue
                    
                df = pd.DataFrame(
                    pnl_data["records"],
                    columns=[item["name"] for item in pnl_data["schema"]["properties"]],
                )
                if df.empty:
                    continue
                    
                df = df.rename(columns={"date": "Date", "pnl": alpha_id})
                df["Date"] = pd.to_datetime(df["Date"])
                df = df[["Date", alpha_id]].set_index("Date")
                dfs.append(df)
            except Exception as e:
                self.logger.error(f"Error processing PnL data for {alpha_id}: {e}")
                
        if dfs:
            for df in dfs:
                df.columns = df.columns.astype(str)
            alpha_pnls = pd.concat(dfs, axis=1, join="outer")
            alpha_pnls.sort_index(inplace=True)
            # 处理可能的列名重复
            alpha_pnls = alpha_pnls.loc[:, ~alpha_pnls.columns.duplicated()]
            return alpha_pnls
            
        return pd.DataFrame()

    def pnl_to_returns(self, pnl_df: pd.DataFrame) -> pd.DataFrame:
        """将 PnL 数据转换为收益率。"""
        return pnl_df - pnl_df.ffill().shift(1)

    def get_alpha_results(self, alpha_id: str|List[str]) -> pd.DataFrame:
        """获取并计算单个或多个 Alpha 的收益率。"""
        if isinstance(alpha_id, str):
            pnl = self._get_alpha_pnl(alpha_id)
        else:
            pnl = self.get_alpha_pnls(alpha_id) 
        if pnl.empty:
            return pd.DataFrame()
            
        returns = self.pnl_to_returns(pnl)
        
        if not returns.empty:
            cutoff_date = returns.index.max() - pd.DateOffset(years=self.retention_years)
            returns = returns[returns.index > cutoff_date]
        
        return returns

    def extract_tokens(
            self,
            expression: str
        ) -> Tuple[List[str], List[str]]:
            """
            从 alpha 表达式中提取使用的算子和数据字段。
            
            Args:
                expression: Alpha 表达式字符串
                
            Returns:
                (operators, datafields): 使用的算子列表和数据字段列表
            """

            cnt = [
                "market",
                "sector",
                "industry",
                "subindustry",
                'exchange',
                'country',
                'currency',
            ]
                
            tokens = set(re.findall(r"[a-zA-Z0-9_.]+", expression))
            
            operators = [f for f in tokens if f in self.operators]
            datafields = sorted([
                f for f in [f for f in tokens if f not in self.operators]
                if not f.isdigit() and len(f) >= 3 and f not in cnt
                and self.dbmanager.field_check(f)
            ])
            
            return operators, datafields
    
    def expression_check(self, express, data_fields_used_list, operators_used_list):
        operators, datafields = self.extract_tokens(express)
        field_not_used = [field for field in datafields if field not in data_fields_used_list]
        operator_not_used = [op for op in operators if op not in operators_used_list]
        return len(field_not_used) != 0, field_not_used, len(operator_not_used) != 0, operator_not_used

    def tag_generator(self, alpha_id, region = None, expression = None, tags=None):
        if region == None or expression == None:
            resp = self.wqbs.locate_alpha(alpha_id, log=None)
            data = resp.json()
            region = data['settings']['region']
            expression = data['regular']['code']
        _, datafields = self.extract_tokens(expression)
        if not tags:
            tags = []
        tags_new = [self.dbmanager.field_category_get(field, region) for field in datafields]
        if tags_new != tags:
            self.update_alpha_metadata(alpha_id, tags_new)
        return tags_new