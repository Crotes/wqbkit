import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 模块级路径变量（向后兼容，初始为 None，由 AlphaBaseCore 实例化时设置）
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path | None = None
DATA_DIR: Path | None = None
LOGS_DIR: Path | None = None


class Config:
    """应用配置，统一读取环境变量。"""

    # -------------------------------------------------------------------------
    # 数据库开关（设为 false 可完全禁用数据库功能，避免强制连接 PostgreSQL）
    # -------------------------------------------------------------------------
    ENABLE_DATABASE: bool = os.getenv("DB_ENABLE", "true").lower() in ("true", "1", "yes")

    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "WorldQuant")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    WQB_USERNAME: str = os.getenv("WQB_USERNAME", "")
    WQB_PASSWORD: str = os.getenv("WQB_PASSWORD", "")
    # 内置常量，不再通过 .env 配置
    WQB_API_BASE_URL: str = "https://api.worldquantbrain.com"
    LOG_LEVEL: str = "INFO"

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

    # 实例级路径属性（由 reload 方法设置）
    project_root: Path = Path.cwd()
    data_dir: Path = Path.cwd() / "data"
    logs_dir: Path = Path.cwd() / "logs"

    def reload(self, project_root: str | Path | None = None) -> None:
        """重新从 os.environ 读取配置，并可指定项目根目录。

        Args:
            project_root: 项目根目录。指定后会同步更新 DATA_DIR / LOGS_DIR
                          以及模块级变量 PROJECT_ROOT / DATA_DIR / LOGS_DIR。
        """
        self.ENABLE_DATABASE = os.getenv("DB_ENABLE", "true").lower() in ("true", "1", "yes")
        self.DB_HOST = os.getenv("DB_HOST", "localhost")
        self.DB_PORT = os.getenv("DB_PORT", "5432")
        self.DB_NAME = os.getenv("DB_NAME", "WorldQuant")
        self.DB_USER = os.getenv("DB_USER", "postgres")
        self.DB_PASSWORD = os.getenv("DB_PASSWORD", "")
        self.WQB_USERNAME = os.getenv("WQB_USERNAME", "")
        self.WQB_PASSWORD = os.getenv("WQB_PASSWORD", "")
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
        self.RETRY_DELAY_BASE = int(os.getenv("RETRY_DELAY_BASE", "2"))
        self.BARK_KEY = os.getenv("BARK_KEY", "")
        self.BARK_BASE_URL = os.getenv("BARK_BASE_URL", "https://api.day.app")
        self.DEFAULT_CONSULTANT_DAY = os.getenv("DEFAULT_CONSULTANT_DAY", "2025-04-19")

        if project_root:
            self.project_root = Path(project_root)
        # 否则保持当前值（由 AlphaBaseCore 的 project_root 参数决定）

        self.data_dir = self.project_root / "data"
        self.logs_dir = self.project_root / "logs"

        # 同步更新模块级变量，确保 logger.py 等模块也能看到正确路径
        global PROJECT_ROOT, DATA_DIR, LOGS_DIR
        PROJECT_ROOT = self.project_root
        DATA_DIR = self.data_dir
        LOGS_DIR = self.logs_dir

    @property
    def DATABASE_URI(self) -> str:
        """组合数据库连接 URI。"""
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


class _DisabledDBClass:
    """占位类：当数据库被禁用时，实例化会抛出清晰的错误提示。"""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError(
            "Database is disabled. Set DB_ENABLE=true in .env to use this feature."
        )


config = Config()
