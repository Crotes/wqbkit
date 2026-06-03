from wqbkit.app.config import config, _DisabledDBClass

if config.ENABLE_DATABASE:
    from .alpha_machine import AlphaMachine
    from .alpha_simulator import AlphaSimulator
else:
    AlphaMachine = _DisabledDBClass  # type: ignore[misc]
    AlphaSimulator = _DisabledDBClass  # type: ignore[misc]
