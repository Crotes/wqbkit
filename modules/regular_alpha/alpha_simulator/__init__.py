from wqbkit.app.config import config

if config.ENABLE_DATABASE:
    from .alpha_simulator import AlphaSimulator
else:
    AlphaSimulator = None  # type: ignore[assignment]
