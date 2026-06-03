"""WorldQuant Brain Alpha Research Toolkit"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("wqbkit")
except PackageNotFoundError:
    __version__ = "0.0.0"

from wqbkit.app.config import config

# 始终可用
from wqbkit.app.core.alpha_base_core import AlphaBaseCore
from wqbkit.app.core.alpha_db_core import AlphaDbCore
from wqbkit.modules.correlation.alpha_calc_corr import AlphaCalcCorr
from wqbkit.modules.super_alpha.alpha_dyeing import AlphaDyeing

# 条件导入：数据库禁用时替换为占位类
if config.ENABLE_DATABASE:
    from wqbkit.modules.regular_alpha.alpha_machine.alpha_machine import AlphaMachine
    from wqbkit.modules.regular_alpha.alpha_simulator.alpha_simulator import AlphaSimulator
    from wqbkit.modules.super_alpha.super_alpha_simulator import SuperAlphaSimulator
    from wqbkit.modules.competitions.Osmosis.osmosis_selector_v3 import OsmosisAlphaSelectorV3
    from wqbkit.modules.competitions.Osmosis.osmosis_allocator_v3 import OsmosisAllocatorV3
    from wqbkit.modules.competitions.Osmosis.osmosis_clear_v3 import OsmosisClearV3
    from wqbkit.modules.competitions.Osmosis.osmosis_runner_v3 import OsmosisRunnerV3
else:
    from wqbkit.app.config import _DisabledDBClass
    AlphaMachine = _DisabledDBClass  # type: ignore[misc]
    AlphaSimulator = _DisabledDBClass  # type: ignore[misc]
    SuperAlphaSimulator = _DisabledDBClass  # type: ignore[misc]
    OsmosisAlphaSelectorV3 = _DisabledDBClass  # type: ignore[misc]
    OsmosisAllocatorV3 = _DisabledDBClass  # type: ignore[misc]
    OsmosisClearV3 = _DisabledDBClass  # type: ignore[misc]
    OsmosisRunnerV3 = _DisabledDBClass  # type: ignore[misc]

__all__ = [
    "AlphaBaseCore",
    "AlphaDbCore",
    "AlphaCalcCorr",
    "AlphaMachine",
    "AlphaSimulator",
    "SuperAlphaSimulator",
    "AlphaDyeing",
    "OsmosisAlphaSelectorV3",
    "OsmosisAllocatorV3",
    "OsmosisClearV3",
    "OsmosisRunnerV3",
    "config",
    "__version__",
]
