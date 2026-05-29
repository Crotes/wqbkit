from typing import List

TS_DAYS: List[int] = [5, 22, 66, 120, 240]
TS_COMP_DAYS: List[int] = [5, 22, 66, 240]

VECTORS: List[str] = ["cap"]

ZERO_ORDER_NUM_OP: List[str] = ["", "arc_tan", "inverse", "log", "round", "round_down", "sqrt"]
ZERO_ORDER_BASE_OP: List[str] = ["", "normalize", "quantile", "rank", "zscore", "scale", "scale_down"]

EXCLUDED_TOKENS: List[str] = ["range", "alpha"]
