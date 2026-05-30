from wqbkit.app.config import config

if config.ENABLE_DATABASE:
    from .alpha_calc_corr import AlphaCalcCorr
else:
    AlphaCalcCorr = None  # type: ignore[assignment]
