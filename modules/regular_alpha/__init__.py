from wqbkit.app.config import config

from .alpha_machine import AlphaGenerator

if config.ENABLE_DATABASE:
    from .alpha_machine import AlphaMachine
    from .alpha_simulator import AlphaSimulator
else:
    AlphaMachine = None  # type: ignore[assignment]
    AlphaSimulator = None  # type: ignore[assignment]
