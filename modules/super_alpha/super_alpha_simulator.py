
import sys
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from threading import current_thread, Event

import pytz
from wqb import FilterRange

from wqbkit.app.config import config
from wqbkit.app.core import AlphaBaseCore, retry_decorator
from wqbkit.app.core.wqb_urls import URL_SIMULATIONS
from wqbkit.app.database import AlphaDBManager, Status


class SuperAlphaSimulator(AlphaBaseCore):
    """
    Super Alpha 模拟器
    
    负责调度和执行 Super Alpha 的模拟任务，管理并发控制、结果处理和异常恢复。
    """
    
    # 常量配置
    MAX_CONCURRENT_TASKS = 2
    DAILY_SIMULATION_LIMIT = 500
    CACHE_DURATION_SECONDS = 60
    POLL_INTERVAL_SECONDS = 10
    LONG_WAIT_SECONDS = 3600
    RETRY_WAIT_SECONDS = 60
    ERROR_WAIT_SECONDS = 30
    NO_ALPHA_WAIT_SECONDS = 10

    def __init__(self):
        """初始化 SUPER Alpha 模拟器。"""
        super().__init__()
        self.max_concurrent = self.MAX_CONCURRENT_TASKS

        self.dbmanager = AlphaDBManager() if config.ENABLE_DATABASE else None

        self.LOG_PREFIX_MAIN = "[主线程]"
        self.LOG_PREFIX_SIM = "[模拟线程-{}]"

        self.shutdown_event = Event()

        self.remaining_simulations = 5000

    def multi_simulate(self, alpha: tuple) -> None:
        """
        执行单个 Super Alpha 的模拟任务。
        
        Args:
            alpha: 包含 (id, selection, combo, alpha_json) 的元组
        """
        thread_name = current_thread().name
        try:
            thread_num = int(thread_name.split('_')[1]) + 1
        except (IndexError, ValueError):
            thread_num = 0

        time_start = datetime.now()
        
        # 解包元组，使用更清晰的变量名
        alpha_db_id, _, _, alpha_json = alpha
        
        log_prefix = self.LOG_PREFIX_SIM.format(thread_num)
        self.logger.info(f'{log_prefix} 开始模拟: {alpha_json}')

        simulation_progress_url = None
        try:
            response = self.post(URL_SIMULATIONS, alpha_json)
            simulation_progress_url = response.headers['Location']
            self.remaining_simulations = int(response.headers.get("x-ratelimit-remaining", 0))

            self.logger.info(f'{log_prefix} {simulation_progress_url}') 
        except Exception as e:
            if self.dbmanager is not None:
                self.dbmanager.superalpha_update_status(alpha_db_id, Status.PENDING)
            self.logger.error(f'{log_prefix} 提交模拟请求失败: {e}, 等待重试')
            if self.shutdown_event.wait(self.RETRY_WAIT_SECONDS):
                return
            return

        while not self.shutdown_event.is_set():
            try:
                simulation_progress = self.get(simulation_progress_url)
            except Exception as e:
                self.logger.error(f'{log_prefix} 获取模拟进度失败: {e}')
                if self.shutdown_event.wait(self.ERROR_WAIT_SECONDS):
                    return
                continue

            time_elapsed = (datetime.now() - time_start).seconds
            
            # 检查 Retry-After 头，如果为 0 表示请求已完成（成功或失败）
            if simulation_progress.headers.get("Retry-After", 0) == 0:
                self.logger.info(f'{log_prefix} 模拟结束, 耗时 {time_elapsed // 60}分{time_elapsed % 60}秒')
                
                info = simulation_progress.json()
                if info.get('status') == 'ERROR':
                    self.logger.error(f'{log_prefix} 模拟状态为 ERROR')
                    if self.dbmanager is not None:
                        self.dbmanager.superalpha_update_status(alpha_db_id, Status.FAILED)
                    return

                try:
                    alpha_id = info.get('alpha')
                    if self.dbmanager is not None:
                        self.dbmanager.superalpha_update_alpha_id(alpha_db_id, alpha_id)
                        self.dbmanager.superalpha_update_status(alpha_db_id, Status.SUCCESS)
                        self.dbmanager.superalpha_update_timeuse(alpha_db_id, time_elapsed)

                    self.update_alpha_metadata(alpha_id, 'own')

                    self.logger.info(f'{log_prefix} 模拟成功: {alpha_id}')
                except Exception as e:
                    self.logger.error(f'{log_prefix} 处理成功结果时出错: {e}')
                
                # 任务完成，退出循环
                return
            else:
                progress = simulation_progress.json().get('progress', 0)
                self.logger.info(f"{log_prefix} 进度 {progress:.1%}, 已耗时 {time_elapsed // 60}分{time_elapsed % 60}秒")
                if self.shutdown_event.wait(self.POLL_INTERVAL_SECONDS):
                    return

    def _process_completed_futures(self, done_futures: set) -> None:
        """处理已完成的任务，捕获并记录可能的异常"""
        for future in done_futures:
            try:
                future.result()
            except Exception as e:
                self.logger.error(f"{self.LOG_PREFIX_MAIN} 任务执行异常: {e}")

    @retry_decorator()
    def get_today_simulations_count(self) -> None:
        """获取今日已创建的 SUPER Alpha 数量（用于限流判断）。"""
        ny_tz = pytz.timezone('America/New_York')
        today_start = datetime.now(ny_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        
        resps = self.wqbs.filter_alphas_limited(
            date_created=FilterRange.from_str(f"[{today_start.isoformat()}, {tomorrow_start.isoformat()})"),
            log=None,
            limit=1,
            type='SUPER',
            offset=0,
        )
        return resps.json()['count']

    def simulator(self) -> None:
        """
        主模拟循环。
        
        启动线程池，从数据库获取任务并分发给工作线程。
        """
        futures = set()  # 用于跟踪活跃的模拟任务
        
        self.logger.info(f"{self.LOG_PREFIX_MAIN} 启动模拟器 (并发数: {self.max_concurrent})")
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            try:
                while not self.shutdown_event.is_set():
                    # 清理已完成的任务
                    done, _ = wait(futures, timeout=0, return_when=FIRST_COMPLETED)
                    self._process_completed_futures(done)
                    futures -= done

                    # 检查是否有空闲线程
                    if len(futures) >= self.max_concurrent:
                        # 等待至少一个任务完成
                        done, _ = wait(futures, return_when=FIRST_COMPLETED)
                        self._process_completed_futures(done)
                        futures -= done
                    
                    if self.remaining_simulations <= 500:
                        if self.get_today_simulations_count() == 0:
                            self.remaining_simulations = 5000
                        else:
                            self.logger.info(f"{self.LOG_PREFIX_MAIN} 今日模拟次数已达上限，等待1小时后继续")
                            self.shutdown_event.wait(1800)
                        continue
                    
                    # 从数据库中提取一个superalpha
                    alpha = self.dbmanager.superalpha_get_pending() if self.dbmanager is not None else None

                    # 如果shutdown被触发（可能在wait期间），则停止提交新任务
                    if self.shutdown_event.is_set():
                        break

                    # 如果数据库中没有alpha
                    if not alpha:
                        if not futures:
                            # 如果没有任务在运行，则等待一段时间后重试
                            self.logger.info(f'{self.LOG_PREFIX_MAIN} 无待处理任务，等待{self.NO_ALPHA_WAIT_SECONDS}秒...')
                            if self.shutdown_event.wait(self.NO_ALPHA_WAIT_SECONDS):
                                break
                        else:
                            # 如果有任务在运行，等待其中一个完成或超时
                            # 这样可以避免在任务运行时频繁查询数据库
                            done, _ = wait(futures, timeout=self.NO_ALPHA_WAIT_SECONDS, return_when=FIRST_COMPLETED)
                            self._process_completed_futures(done)
                            futures -= done
                        continue

                    #将提取的alpha交给多线程处理
                    future = executor.submit(
                        self.multi_simulate,
                        alpha=alpha,
                    )
                    futures.add(future)
            except KeyboardInterrupt:
                self.logger.info("接收到中断信号，正在关闭...")
                self.shutdown_event.set()
            except Exception as e:
                self.logger.error(f"模拟器发生未捕获异常: {e}")
                self.shutdown_event.set()
            finally:
                self.logger.info("开始优雅关闭流程...")
                self.logger.info("等待所有模拟任务完成...")
                # ThreadPoolExecutor context manager will call shutdown(wait=True) automatically
                executor.shutdown(wait=True)
                self.logger.info("所有模拟任务已完成")
                self.logger.info("SuperAlphaSimulator 已安全关闭")
