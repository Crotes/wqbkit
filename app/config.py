import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录（wqbkit/app/config.py -> app -> wqbkit -> root）
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"


class Config:
    """应用配置，统一读取环境变量。"""

    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "WorldQuant")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    WQB_USERNAME: str = os.getenv("WQB_USERNAME", "")
    WQB_PASSWORD: str = os.getenv("WQB_PASSWORD", "")
    WQB_API_BASE_URL: str = os.getenv("WQB_API_BASE_URL", "https://api.worldquantbrain.com")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "5"))
    RETRY_DELAY_BASE: int = int(os.getenv("RETRY_DELAY_BASE", "2"))

    BARK_KEY: str = os.getenv("BARK_KEY", "")
    BARK_BASE_URL: str = os.getenv("BARK_BASE_URL", "https://api.day.app")

    DEFAULT_CONSULTANT_DAY: str = os.getenv("DEFAULT_CONSULTANT_DAY", "2025-04-19")

    # -------------------------------------------------------------------------
    # 应用级统一常量（非 env，集中管理以避免跨模块重复硬编码）
    # -------------------------------------------------------------------------
    MAX_WORKERS: int = 10
    TOTAL_SCORE: int = 100_000
    DEFAULT_PAGE_LIMIT: int = 100
    DEFAULT_PAGE_OFFSET: int = 0
    DEFAULT_DYEING_WORKERS: int = 3

    @property
    def DATABASE_URI(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


config = Config()
