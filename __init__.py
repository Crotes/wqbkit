"""WorldQuant Brain Alpha Research Toolkit"""

from wqbkit.app.config import PROJECT_ROOT
from dotenv import load_dotenv

# 显式加载项目根目录的 .env（适用于 editable install 模式）
# load_dotenv 默认 override=False，不会覆盖已存在的环境变量
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("wqbkit")
except PackageNotFoundError:
    __version__ = "0.0.0"

# ---------- Public API ----------
# 核心基础设施
from wqbkit.app.core.alpha_base_core import AlphaBaseCore
from wqbkit.app.core.alpha_db_core import AlphaDbCore

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
from wqbkit.modules.competitions.Osmosis.osmosis_selector_v3 import OsmosisAlphaSelectorV3
from wqbkit.modules.competitions.Osmosis.osmosis_allocator_v3 import OsmosisAllocatorV3
from wqbkit.modules.competitions.Osmosis.osmosis_clear_v3 import OsmosisClearV3
from wqbkit.modules.competitions.Osmosis.osmosis_runner_v3 import OsmosisRunnerV3

__all__ = [
    "__version__",
    # 核心
    "AlphaBaseCore",
    "AlphaDbCore",
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
    # Osmosis V3
    "OsmosisAlphaSelectorV3",
    "OsmosisAllocatorV3",
    "OsmosisClearV3",
    "OsmosisRunnerV3",
]
