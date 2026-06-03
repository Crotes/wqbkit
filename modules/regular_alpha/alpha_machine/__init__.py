from wqbkit.app.config import config, _DisabledDBClass

if config.ENABLE_DATABASE:
    from .alpha_machine import AlphaMachine
else:
    AlphaMachine = _DisabledDBClass  # type: ignore[misc]
