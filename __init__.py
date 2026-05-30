"""WorldQuant Brain Alpha Research Toolkit"""

import os
from dotenv import load_dotenv

# 显式加载项目根目录的 .env（适用于 editable install 模式）
# load_dotenv 默认 override=False，不会覆盖已存在的环境变量
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

__version__ = "0.2.2"

# ---------- Public API ----------
# 核心基础设施
from wqbkit.app.core.alpha_base_core import AlphaBaseCore
from wqbkit.app.core.alpha_db_core import AlphaDbCore
from wqbkit.app.core.decorators import retry_decorator
from wqbkit.app.database.alpha_db_manager import AlphaDBManager

# 数据模型
from wqbkit.app.database import schemas

# 业务模块
from wqbkit.modules.correlation.alpha_calc_corr import AlphaCalcCorr
from wqbkit.modules.regular_alpha.alpha_machine.alpha_generator import AlphaGenerator
from wqbkit.modules.regular_alpha.alpha_machine.alpha_machine import AlphaMachine
from wqbkit.modules.regular_alpha.alpha_simulator.alpha_simulator import AlphaSimulator
from wqbkit.modules.super_alpha.alpha_dyeing import AlphaDyeing
from wqbkit.modules.super_alpha.super_alpha_simulator import SuperAlphaSimulator
from wqbkit.modules.message.alpha_message_sender import sc_send

__all__ = [
    "__version__",
    # 核心
    "AlphaBaseCore",
    "AlphaDbCore",
    "AlphaDBManager",
    "retry_decorator",
    # 数据模型
    "schemas",
    # 业务模块
    "AlphaCalcCorr",
    "AlphaGenerator",
    "AlphaMachine",
    "AlphaSimulator",
    "AlphaDyeing",
    "SuperAlphaSimulator",
    "sc_send",
]
