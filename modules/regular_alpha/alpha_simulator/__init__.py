from wqbkit.app.config import config, _DisabledDBClass

if config.ENABLE_DATABASE:
    from .alpha_simulator import AlphaSimulator
else:
    AlphaSimulator = _DisabledDBClass  # type: ignore[misc]
