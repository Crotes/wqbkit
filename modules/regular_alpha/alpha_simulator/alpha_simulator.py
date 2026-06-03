from pathlib import Path
import signal
import json
import os
from queue import Queue, Empty
from threading import current_thread, Event

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from time import sleep
from typing import Optional, List, Dict, Tuple

import pytz
from pytz import timezone
from wqb import FilterRange

from wqbkit.app.core.alpha_db_core import AlphaDbCore
from wqbkit.app.core.decorators import retry_decorator
from wqbkit.app.core.wqb_urls import URL_ALPHAS_ALPHAID, URL_SIMULATIONS
from wqbkit.app.config import config
from wqbkit.app.database import Status, FactorData, SimulationData

# 获取美国东部时间
eastern = timezone("US/Eastern")
fmt = "%Y-%m-%d"
loc_dt_fmt = datetime.now(eastern).strftime(fmt)


class AlphaSimulator(AlphaDbCore):
    def __init__(self, limit_of_multi_simulations: int, limit_of_children_simulations: int, project_root: str | Path | None = None):
        """
        初始化Alpha模拟器

        Args:
            limit_of_multi_simulations: 多模拟的限制数量
            limit_of_children_simulations: 子模拟的限制数量
        """
        super().__init__(project_root)
        self.limit_of_multi_simulations = limit_of_multi_simulations
        self.limit_of_children_simulations = limit_of_children_simulations
        self.max_concurrent = limit_of_multi_simulations
        # 添加结果处理线程池的大小
        self.max_result_processors = limit_of_multi_simulations
        # 添加一个队列用于存储需要处理的模拟结果
        self.result_queue = Queue()
        self.result_set = set()
        # 添加优雅退出控制事件
        self.simulate_shutdown_event = Event()
        self.process_shutdown_event = Event()
        
        # 定义日志前缀格式
        self.LOG_PREFIX_MAIN = "[主线程]"
        self.LOG_PREFIX_SIM = "[模拟线程-{}]"
        self.LOG_PREFIX_RESULT = "[结果处理线程-{}]"

        self.today_count = 0

        self.remaining_simulations = 4500
        
        # 初始化线程池
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="SimWorker")
        self.result_executor = ThreadPoolExecutor(max_workers=self.max_result_processors, thread_name_prefix="ResultWorker")
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 启动结果处理线程
        self.logger.info(f"{self.LOG_PREFIX_MAIN} 启动{self.max_result_processors}个结果处理线程")
        for _ in range(self.max_result_processors):
            self.result_executor.submit(self.process_simulation_results)

    def _load_config(self, filename: str) -> Dict:
        """加载配置文件"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), filename)
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                self.logger.warning(f"配置文件未找到: {config_path}")
                return {}
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            return {}

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM" if signum == signal.SIGTERM else str(signum)
        self.logger.info(f"{self.LOG_PREFIX_MAIN} 接收到信号 {sig_name}，正在准备优雅退出，请等待当前正在运行的任务完成...")
        self.simulate_shutdown_event.set()

    def normalize_alpha_string(self, alpha_str: str) -> Optional[str]:
        """标准化alpha字符串，移除多余的空白字符"""
        # 移除所有空白字符（空格、换行、制表符等）
        return "".join(alpha_str.split())

    DEFAULT_SETTINGS = {
        "instrumentType": "EQUITY",
        "truncation": 0.02,
        "pasteurization": "ON",
        "unitHandling": "VERIFY",
        "nanHandling": "OFF",
        "language": "FASTEXPR",
        "visualization": False,
        "maxTrade": "OFF",
    }

    def combine_alpha(self, expression: str, region: str, universe: str, neutralization: str, decay: int, delay: int) -> Optional[Dict]:
        """将表达式和设置组合为 WQB API 所需的 Alpha 请求体。"""
        settings = self.DEFAULT_SETTINGS.copy()
        settings.update({
            "region": region,
            "universe": universe,
            "delay": delay,
            "decay": decay,
            "neutralization": neutralization,
        })
        
        alpha = {
            "type": "REGULAR",
            "settings": settings,
            "regular": expression,
        }

        if region == 'ASI':
            alpha['settings']['maxTrade'] = 'ON'
            
        return alpha
    
    def alpha_factor_key(self, alpha_factor_info: FactorData) -> Optional[str]:
        """生成 Alpha 的唯一标识键（标准化后的表达式+设置拼接）。"""
        return self.normalize_alpha_string(f"{alpha_factor_info.pre}{alpha_factor_info.expression}{alpha_factor_info.region}{alpha_factor_info.universe}{alpha_factor_info.neutralization}{alpha_factor_info.decay}")

    def generate_alpha(self, alpha_list: List[FactorData]) -> Tuple[Optional[List[Dict]], Optional[Dict[str, FactorData]], Optional[List[int]]]:
        """将 FactorData 列表去重并转换为 WQB 批量模拟请求体。"""
        try:
            alpha_to_info = {} 
            factor_id_list = []
            alpha_setting_list = []
            delay = 1

            for item in alpha_list:
                # factor_id, pre, expression, neutralization, region, universe, decay, task_id, priority, generation, tag = item
                factor_id = item.factor_id
                pre = item.pre
                expression = item.expression
                neutralization = item.neutralization
                region = item.region
                universe = item.universe
                decay = item.decay
                
                # 标准化alpha字符串
                base_alpha = pre + expression
                alpha_key = self.alpha_factor_key(item)

                alpha_to_info[alpha_key] = item

                factor_id_list.append(factor_id)

                alpha_setting_list.append(
                    self.combine_alpha(base_alpha, region, universe, neutralization, decay, delay)
                )

            return alpha_setting_list, alpha_to_info, factor_id_list
        except Exception as e:
            self.logger.error(f"generate_alpha失败，错误信息：{e}")
            return None, None, None
        
    def _safe_get(self, data: dict, *keys, default=None):
        """安全获取嵌套字典的值"""
        result = data
        for key in keys:
            if isinstance(result, dict):
                result = result.get(key)
            else:
                return default
        return result if result is not None else default

    def _create_empty_simulation_result(self, alpha_id: str = "") -> SimulationData:
        """创建空的模拟结果对象"""
        return SimulationData(
            alpha_id=alpha_id, 
            expression="", 
            region="", 
            universe="", 
            neutralization="", 
            decay=0, 
            delay=0, 
            sharpe=0.0, 
            fitness=0.0, 
            drawdown=0.0, 
            twoyearsharpe=0.0, 
            fail_num=0
        )

    @retry_decorator()
    def get_simulation_result(self, url: str) -> Optional[SimulationData]:
        """获取模拟结果 - 安全处理所有可能的键不存在情况"""
        try:
            # 1. 获取初始响应数据
            response = self.get(url)
            if not response or not response.ok:
                return self._create_empty_simulation_result()
            
            alpha_data = response.json()
            if not isinstance(alpha_data, dict):
                return self._create_empty_simulation_result()
            
            # 2. 安全提取alpha_id
            alpha_id = self._safe_get(alpha_data, "alpha", default="")
            
            # 3. 获取详细数据
            data_response = self.get(URL_ALPHAS_ALPHAID.format(alpha_id))
            if not data_response or not data_response.ok:
                return self._create_empty_simulation_result(alpha_id)
            
            data = data_response.json()
            if not isinstance(data, dict):
                return self._create_empty_simulation_result(alpha_id)
            
            # 4. 安全提取所有字段
            expression = self._safe_get(data, "regular", "code", default="")
            settings = self._safe_get(data, "settings", default={})
            
            region = self._safe_get(settings, "region", default="")
            universe = self._safe_get(settings, "universe", default="")
            neutralization = self._safe_get(settings, "neutralization", default="")
            decay = self._safe_get(settings, "decay", default="")
            delay = self._safe_get(settings, "delay", default="")
            
            alpha_is = self._safe_get(data, "is", default={})
            
            sharpe = self._safe_get(alpha_is, "sharpe", default=0)
            try:
                sharpe = float(sharpe) if sharpe else 0
            except (ValueError, TypeError):
                sharpe = 0
            
            fitness = self._safe_get(alpha_is, "fitness", default=0)
            try:
                fitness = float(fitness) if fitness else 0
            except (ValueError, TypeError):
                fitness = 0
            
            drawdown = self._safe_get(alpha_is, "drawdown")
            if drawdown is not None:
                try:
                    drawdown = float(drawdown)
                except (ValueError, TypeError):
                    drawdown = None
            
            # 5. 安全提取twoyearsharpe
            checks = self._safe_get(alpha_is, "checks", default=[])
            twoyearsharpe = 0
            if isinstance(checks, list):
                for check in checks:
                    if (isinstance(check, dict) and 
                        check.get("name") in {"LOW_2Y_SHARPE", "IS_LADDER_SHARPE"}):
                        value = check.get("value")
                        if value is not None:
                            try:
                                twoyearsharpe = float(value)
                            except (ValueError, TypeError):
                                twoyearsharpe = 0
                        break
            
            # 6. 安全计算fail_num
            fail_num = 0
            if isinstance(checks, list):
                for item in checks:
                    if isinstance(item, dict) and item.get("result") == "FAIL":
                        fail_num += 1

            simulation_result = SimulationData(
                alpha_id=alpha_id, 
                expression=expression, 
                region=region, 
                universe=universe, 
                neutralization=neutralization,
                decay=decay,
                delay=delay,
                sharpe=sharpe, 
                fitness=fitness, 
                drawdown=drawdown, 
                twoyearsharpe=twoyearsharpe, 
                fail_num=fail_num
            )

            return simulation_result
        
        except Exception as e:
            self.logger.error(f"get_simulation_result失败，错误信息：{e}")
            return self._create_empty_simulation_result()


    def check_zero(self, alpha_id: str) -> Optional[int]:
        """检查 Alpha 近 5 年 yearly stats 是否有零值（fitness/sharpe 为 0）。"""
        resp = self.get(
            f"{config.WQB_API_BASE_URL}/alphas/{alpha_id}/recordsets/yearly-stats"
        )
        records = resp.json()["records"]
        for record in records[5:]:
            if record[3] == 0 or record[4] == 0:
                return 0
        return 1

    def score_alpha_comprehensive(self, alpha_info: SimulationData):
        """综合评分函数"""
        # 预先过滤显然无效的alpha，避免额外的API调用
        if alpha_info.fitness <= 0:
             return 0
        return self.check_zero(alpha_info.alpha_id)

    def _process_error_simulation(self, simulation_progress_url):
        """处理模拟失败/错误状态的占位方法。"""
        pass

    def _wait_for_simulation(self, simulation_progress_url: str, log_prefix: str, factor_id_list: List[str] = None) -> Tuple[bool, Optional[str]]:
        """统一的模拟等待逻辑"""
        time_start = datetime.now()
        while True:
            try:
                simulation_progress = self.wqbs.get(simulation_progress_url)
            except Exception as e:
                self.logger.error(f"{log_prefix} {simulation_progress_url} 获取模拟进度失败: {e}")
                sleep(30)
                continue

            timeuse = (datetime.now() - time_start).seconds
            
            if simulation_progress.headers.get("Retry-After", 0) == 0:
                self.logger.info(f"{log_prefix} {simulation_progress_url} 模拟完成, 耗时 {timeuse // 60} 分 {timeuse % 60} 秒")
                status = simulation_progress.json().get("status")
                
                if status == "ERROR":
                    self.logger.error(f"{log_prefix} {simulation_progress_url} 模拟出错")
                    if factor_id_list:
                        self.dbmanager.alphafactor_bulk_update_status(factor_id_list, Status.FAILED)
                    return False, None
                
                return True, simulation_progress
            else:
                progress = simulation_progress.json().get("progress")
                self.logger.warning(
                    f"{log_prefix} {simulation_progress_url} 模拟未完成, 进度 {progress}, 已耗时 {timeuse // 60} 分 {timeuse % 60} 秒"
                )

                if (timeuse // 60 >= 60) or (timeuse // 60 >= 10 and progress == 0.1):
                    self.delete(simulation_progress_url)
                    self.logger.error(f"{log_prefix} 模拟超时, 已删除模拟任务")
                    if factor_id_list:
                        self.dbmanager.alphafactor_bulk_update_status(factor_id_list, Status.WARNING)
                    return False, None
                
                if progress <= 0.35:
                    sleep(60)
                else:
                    sleep(10)

    def single_simulate(self, alpha_data: FactorData):
        """单 Alpha 模拟：提交单个 Alpha 到 WQB 并等待结果。"""
        thread_name = current_thread().name
        thread_num = int(thread_name.split("_")[1]) + 1
        log_prefix = self.LOG_PREFIX_SIM.format(thread_num)
        self.logger.info(f"{log_prefix} {alpha_data}")

        alpha = self.combine_alpha(alpha_data.pre + alpha_data.expression, alpha_data.region, alpha_data.universe, alpha_data.neutralization, alpha_data.decay, 1)
        self.logger.info(f"{log_prefix} {alpha}")

        try:
            response = self.post(URL_SIMULATIONS, alpha)
            simulation_progress_url = response.headers["Location"]
            
            # Rate limit logging (Standardized with multi_simulate)
            self.remaining_simulations = remaining = int(response.headers.get("x-ratelimit-remaining", 0))
            self.logger.info(f"{log_prefix} {simulation_progress_url}，今日剩余 {remaining} 次模拟")
            
            success, simulation_progress = self._wait_for_simulation(simulation_progress_url, log_prefix, [alpha_data.factor_id])
            
            if success and simulation_progress:
                # 构造单任务的结果结构，复用处理逻辑
                self.result_queue.put({
                    "childrens": [simulation_progress.json()["id"]], # 单任务直接用ID
                    "alpha_to_info": {self.alpha_factor_key(alpha_data): alpha_data},
                    "factor_id_list": [alpha_data.factor_id],
                    "thread_num": thread_num,
                    "simulation_progress_url": simulation_progress_url,
                    "sim_log_prefix": log_prefix,
                })
                self.logger.info(f"{log_prefix} 已将模拟结果添加到处理队列")
                
        except Exception as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                 pass # Rate limit handling logic if needed
            self.dbmanager.alphafactor_update_status(alpha_data.factor_id, Status.PENDING)
            self.logger.error(f"{log_prefix} 本次模拟失败: {e}, 等待300秒")
            sleep(300)

    def multi_simulate(self, alpha_list_pre: List[FactorData]):
        """批量 Alpha 模拟：提交组合 Alpha 到 WQB 并等待结果。"""
        thread_name = current_thread().name
        thread_num = int(thread_name.split("_")[1]) + 1
        log_prefix = self.LOG_PREFIX_SIM.format(thread_num)

        alpha_list, alpha_to_info, factor_id_list = self.generate_alpha(alpha_list_pre)
        self.logger.info(f"{log_prefix} {alpha_list}")

        try:
            response = self.post(URL_SIMULATIONS, alpha_list)
            simulation_progress_url = response.headers["Location"]
            
            # Rate limit logging
            self.remaining_simulations = remaining = int(response.headers.get("x-ratelimit-remaining", 0))
            self.logger.info(f"{log_prefix} {simulation_progress_url}，今日剩余 {remaining} 次模拟")

            time_start = datetime.now()

            success, simulation_progress = self._wait_for_simulation(simulation_progress_url, log_prefix, factor_id_list)

            if success and simulation_progress:
                try:
                    childrens = simulation_progress.json().get("children")
                    self.result_queue.put({
                        "childrens": childrens,
                        "alpha_to_info": alpha_to_info,
                        "factor_id_list": factor_id_list,
                        "thread_num": thread_num,
                        "simulation_progress_url": simulation_progress_url,
                        "sim_log_prefix": log_prefix,
                    })
                    self.logger.info(f"{log_prefix} 已将模拟结果添加到处理队列")
                except Exception as e:
                    self.logger.error(f"{log_prefix} 处理模拟结果出错 {e}")

        except Exception as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                 # Rate limit handling logic...
                 pass # Simplified for brevity, retaining original logic structure if needed
            self.dbmanager.alphafactor_bulk_update_status(factor_id_list, Status.WARNING)
            self.logger.error(f"{log_prefix} 本次模拟失败: {e}, 等待300秒")
            sleep(300)


        timeuse = (datetime.now() - time_start).seconds
        self.logger.info(f"{log_prefix} 模拟完成，等待结果处理线程池处理结果, 耗时 {timeuse // 60} 分 {timeuse % 60} 秒")

    def _process_single_result(self, url: str, alpha_to_info: Dict, log_prefix: str) -> None:
        """处理单个模拟结果的核心逻辑"""
        try:
            simulation_result = self.get_simulation_result(url)
            if simulation_result is None:
                return

            normalized_alpha = self.normalize_alpha_string(f"{simulation_result.expression}{simulation_result.region}{simulation_result.universe}{simulation_result.neutralization}{simulation_result.decay}")
            factor_info = alpha_to_info.get(normalized_alpha)
            
            if not factor_info:
                self.logger.error(f"{log_prefix} 无法找到对应的alpha信息: {normalized_alpha}")
                return

            alpha_score = self.score_alpha_comprehensive(simulation_result)
            self.tag_generator(
                alpha_id=simulation_result.alpha_id, 
                region=simulation_result.region,
                expression=simulation_result.expression,
                tags=[factor_info.tag]
            )
            self.update_alpha_metadata(simulation_result.alpha_id, tag=factor_info.tag)

            if alpha_score == 0:
                self.hidden_alpha(simulation_result.alpha_id)
                self.logger.info(f"{log_prefix} {url} end: 当前模拟处理完成")
                return

            # 更新结果对象
            simulation_result.pre = factor_info.pre
            simulation_result.score = alpha_score
            simulation_result.priority = factor_info.priority
            simulation_result.task_id = factor_info.task_id
            simulation_result.generation = factor_info.generation
            simulation_result.tag = factor_info.tag

            self.dbmanager.alphasimulated_insert(simulation_result)

            # 模拟反转逻辑
            if simulation_result.sharpe <= -0.5:
                self.dbmanager.alphafactor_insert(FactorData(
                    factor_id=None,
                    pre=factor_info.pre,
                    expression=f"-({factor_info.expression})",
                    region=factor_info.region,
                    universe=factor_info.universe,
                    neutralization=factor_info.neutralization,
                    decay=factor_info.decay,
                    priority=factor_info.priority,
                    task_id=factor_info.task_id,
                    generation=factor_info.generation,
                    tag=factor_info.tag
                ))

            if simulation_result.twoyearsharpe < 0:
                self.hidden_alpha(simulation_result.alpha_id)

            # 多项中性化逻辑
            neutralization_settings = self._load_config('neutralization.json')
            neut_base = neutralization_settings.get(factor_info.region).get('base')
            neut_other = neutralization_settings.get(factor_info.region).get('other')

            if simulation_result.sharpe >= 1 and factor_info.neutralization == neut_base:
                self.dbmanager.alphafactor_bulk_insert([
                    FactorData(
                        factor_id=None,
                        pre=factor_info.pre,
                        expression=factor_info.expression,
                        region=factor_info.region,
                        universe=factor_info.universe,
                        neutralization=neut,
                        decay=4,
                        priority=factor_info.priority,
                        task_id=factor_info.task_id,
                        generation=factor_info.generation,
                        tag=factor_info.tag
                    ) for neut in neut_other
                ])

            self.logger.info(f"{log_prefix} {url} end: 当前模拟处理完成")

        except Exception as e:
            self.logger.error(f"{log_prefix} {url} 获取模拟结果出错: {e}")

    def process_simulation_results(self):
        """处理模拟结果的线程函数"""
        thread_name = current_thread().name
        thread_num = int(thread_name.split("_")[1]) + 1
        log_prefix = self.LOG_PREFIX_RESULT.format(thread_num)
        self.logger.info(f"{log_prefix} 启动")

        while (not self.process_shutdown_event.is_set()) or (not self.result_queue.empty()):
            added_to_result_set = False
            try:
                result_info = self.result_queue.get(timeout=1)

                time_start = datetime.now()
                self.result_set.add(thread_num)
                added_to_result_set = True

                childrens = result_info["childrens"]
                alpha_to_info = result_info["alpha_to_info"]
                factor_id_list = result_info["factor_id_list"]
                orig_thread_num = result_info["thread_num"]
                simulation_progress_url = result_info["simulation_progress_url"]
                sim_log_prefix = result_info["sim_log_prefix"]

                self.logger.info(f"{log_prefix} 开始处理来自{sim_log_prefix}的模拟结果: {simulation_progress_url}")

                for children in childrens:
                    url = f"{URL_SIMULATIONS}/{children}"
                    self._process_single_result(url, alpha_to_info, log_prefix)

                self.dbmanager.alphafactor_bulk_update_status(factor_id_list, Status.SUCCESS)

                timeuse = (datetime.now() - time_start).seconds
                self.logger.info(f"{log_prefix} 处理完成来自线程-{orig_thread_num}的模拟结果, 耗时 {timeuse // 60} 分 {timeuse % 60} 秒")
            except Empty:
                sleep(5)
                continue
            except Exception as e:
                sleep(5)
                self.logger.error(f"{log_prefix} 处理模拟结果时出错: {e}")
            finally:
                if added_to_result_set:
                    self.result_set.discard(thread_num)
        self.logger.info(f"{log_prefix} 退出")
    @retry_decorator()
    def get_today_simulations_count(self):
        """获取今日已创建的 REGULAR Alpha 数量（用于限流判断）。"""
        ny_tz = pytz.timezone('America/New_York')
        today_start = datetime.now(ny_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        resps = self.wqbs.filter_alphas_limited(
            date_created=FilterRange.from_str(f"[{today_start.isoformat()}, {tomorrow_start.isoformat()})"),
            log=None,
            limit=1,
            type='REGULAR',
            offset=0,
        )
        return resps.json()['count']
    
    def simulator(self):
        """多Alpha因子模拟"""
        future_cost_map = {}   # future -> cost
        used_slots = 0
        simulate_num = 0

        try:
            while not self.simulate_shutdown_event.is_set():
                # 清理已完成的任务，并释放额度
                done_futures = [f for f in future_cost_map if f.done()]
                for f in done_futures:
                    cost = future_cost_map.pop(f)
                    used_slots -= cost
                    try:
                        f.result()
                        self.logger.debug(f"{self.LOG_PREFIX_MAIN} 一个任务已完成，释放 {cost} 个线程额度")
                    except Exception as e:
                        self.logger.error(f"{self.LOG_PREFIX_MAIN} 任务执行出错: {e}")

                # 检查是否有空闲线程
                if used_slots >= self.max_concurrent:
                    self.simulate_shutdown_event.wait(30)
                    continue

                if self.remaining_simulations <= 0+self.limit_of_multi_simulations*self.limit_of_children_simulations:
                    if self.get_today_simulations_count() == 0:
                        self.remaining_simulations = 5000
                    else:
                        self.logger.info(f"{self.LOG_PREFIX_MAIN} 今日模拟次数已达上限，等待1小时后继续")
                        self.simulate_shutdown_event.wait(1800)
                        status, msg = self.dbmanager.alphafactor_reset_status()
                        if status:
                            self.logger.info('alpha_factors 数据库刷新成功')
                        else:
                            self.logger.error(f'alpha_factors 数据库刷新失败，失败原因 {msg}')
                    continue

                # 从数据库中提取一批alpha
                self.logger.info(f"{self.LOG_PREFIX_MAIN} 寻找一批次alpha")
                alpha_list = self.dbmanager.alphafactor_get_by_priority_and_time(limit=self.limit_of_children_simulations)

                # 如果shutdown被触发（可能在wait期间），则停止提交新任务
                if self.simulate_shutdown_event.is_set():
                    break
                    
                self.logger.info(f"{self.LOG_PREFIX_MAIN} 找到{len(alpha_list)}个alpha")
                simulate_num += len(alpha_list)

                # 如果没有alpha则等待线程完成
                if not alpha_list:
                    self.logger.warning('数据库数据为空，等待60秒')
                    self.simulate_shutdown_event.wait(60)
                    continue
                
                # 决定任务需要多少线程额度
                if alpha_list[0].region == 'GLB':
                    task_cost = 2
                else:
                    task_cost = 1   # 你可以按业务改成条件判断

                # 如果当前额度不够，就先等
                if used_slots + task_cost > self.max_concurrent:
                    self.logger.info(
                        f"{self.LOG_PREFIX_MAIN} 当前已占用 {used_slots}/{self.max_concurrent}，"
                        f"新任务需要 {task_cost} 个线程额度，打回数据库并等待"
                    )
                    for task in alpha_list:
                        self.dbmanager.alphafactor_update_status(task.factor_id, Status.PENDING)
                    self.simulate_shutdown_event.wait(30)
                    continue

                if len(alpha_list) == 1:
                    future = self.executor.submit(
                        self.single_simulate,
                        alpha_data=alpha_list[0],
                    )
                else:
                    # 将提取的alpha交给多线程处理
                    future = self.executor.submit(
                        self.multi_simulate,
                        alpha_list_pre=alpha_list,
                    )

                future_cost_map[future] = task_cost
                used_slots += task_cost

                self.logger.info(
                    f"{self.LOG_PREFIX_MAIN} 已提交任务，占用 {task_cost} 个线程额度，"
                    f"当前已占用 {used_slots}/{self.max_concurrent}"
                )
        
        except KeyboardInterrupt:
            self.logger.info("接收到KeyboardInterrupt，正在关闭...")
            self.simulate_shutdown_event.set()
        except Exception as e:
            self.logger.error(f"模拟器发生未捕获异常: {e}")
            self.simulate_shutdown_event.set()
        finally:
            self.logger.info("开始优雅关闭流程...")
            
            # 1. 等待所有模拟任务完成
            self.logger.info("等待所有模拟任务完成...")
            self.executor.shutdown(wait=True)
            self.logger.info("所有模拟任务已完成")
            
            # 2. 发送 Sentinel 给结果处理线程
            self.logger.info("通知结果处理线程退出...")
            self.process_shutdown_event.set()
            
            # 3. 等待结果处理线程退出
            self.result_executor.shutdown(wait=True)
            self.logger.info("所有结果处理线程已退出")
            self.logger.info("AlphaSimulator 已安全关闭")

            return simulate_num 