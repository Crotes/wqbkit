"""
应用的日志配置和工厂。
"""
import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from wqbkit.app.config import config


def get_logger(name: str) -> logging.Logger:
    """创建或获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        logging.Logger: 配置好的日志记录器实例
    """
    logger = logging.getLogger(name)
    
    # 如果已经有处理器，说明已经配置过，直接返回
    if logger.handlers:
        return logger

    # 设置日志级别
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # 定义日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 1. 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. 文件处理器 (带自动轮转)
    try:
        # 获取项目根目录: app/core/logger.py -> app/core -> app -> root
        project_root = Path(__file__).resolve().parents[2]
        log_dir = project_root / 'logs' / name
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用 TimedRotatingFileHandler 实现按天轮转
        log_file = log_dir / f'{name}.log'
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when='midnight',
            interval=1,
            backupCount=30,  # 保留最近30天的日志
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"  # 设置轮转文件后缀
        logger.addHandler(file_handler)
    except Exception as e:
        # 如果文件日志设置失败，记录到控制台但不中断程序
        console_handler.setLevel(logging.WARNING)
        logger.warning(f"无法初始化文件日志处理器: {e}")
        
    return logger
