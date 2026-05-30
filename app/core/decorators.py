"""
应用的核心装饰器。
包括重试逻辑和错误处理装饰器。
"""
import functools
import logging
import time
from typing import Callable, Tuple, Type, Union

from wqbkit.app.config import config


def retry_decorator(
    max_retries: int = config.MAX_RETRIES,
    delay_base: int = config.RETRY_DELAY_BASE,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception
) -> Callable:
    """通用重试装饰器。
    
    用于处理网络请求等不稳定操作的自动重试机制，支持指数退避策略。
    
    Args:
        max_retries (int): 最大重试次数
        delay_base (int): 重试延迟的基数（用于指数退避）
        exceptions (Union[Type[Exception], Tuple[Type[Exception], ...]]): 需要捕获并重试的异常类型，默认为 Exception
    
    Returns:
        Callable: 装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        """接收被装饰函数，返回带重试逻辑的包装函数。"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """执行被装饰函数，捕获指定异常并按指数退避策略重试。"""
            # 尝试获取 logger
            logger = logging.getLogger(func.__module__)
            if args and hasattr(args[0], 'logger'):
                logger = args[0].logger
            
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries > max_retries:
                        # 超过最大重试次数，记录错误并抛出异常
                        error_msg = f"函数 {func.__name__} 在重试 {max_retries} 次后失败: {str(e)}"
                        logger.error(error_msg)
                        raise

                    # 计算等待时间
                    wait_time = delay_base ** retries
                    logger.warning(
                        f"函数 {func.__name__} 第 {retries}/{max_retries} 次尝试失败: {str(e)}. "
                        f"将在 {wait_time} 秒后重试..."
                    )
                    time.sleep(wait_time)
        return wrapper
    return decorator
