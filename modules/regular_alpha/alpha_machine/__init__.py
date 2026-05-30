from .alpha_generator import AlphaGenerator

from wqbkit.app.config import config

if config.ENABLE_DATABASE:
    from .alpha_machine import AlphaMachine
else:
    AlphaMachine = None  # type: ignore[assignment]
