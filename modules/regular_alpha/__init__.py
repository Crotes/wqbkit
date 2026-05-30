from wqbkit.app.config import config, _DisabledDBClass

from .alpha_machine import AlphaGenerator

if config.ENABLE_DATABASE:
    from .alpha_machine import AlphaMachine
    from .alpha_simulator import AlphaSimulator
else:
    AlphaMachine = _DisabledDBClass  # type: ignore[misc]
    AlphaSimulator = _DisabledDBClass  # type: ignore[misc]
