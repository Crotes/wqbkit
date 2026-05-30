from .alpha_dyeing import AlphaDyeing
from .super_alpha_creator import SuperAlphaCreator

from wqbkit.app.config import config, _DisabledDBClass

if config.ENABLE_DATABASE:
    from .super_alpha_simulator import SuperAlphaSimulator
else:
    SuperAlphaSimulator = _DisabledDBClass  # type: ignore[misc]
