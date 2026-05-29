# 基础操作列表
MATH_OPS = [
]

BASIC_OPS = [
    'abs',
    'arc_tan', 
    'log', 
    'pasteurize', 
    'purify', 
    'round', 
    'round_down', 
    's_log_1p',
    'sigmoid',
    'sqrt',
    'tanh',
    "inverse", 
    "normalize", 
    "quantile", 
    "rank", 
    "reverse", 
    "zscore"
]

# 时序操作列表
TS_OPS = [
    'inst_tvr',
    "jump_decay",
    "ts_arg_max",
    "ts_arg_min",
    "ts_av_diff",
    "ts_count_nans",
    "ts_decay_linear",
    "ts_delay",
    "ts_delta",
    'ts_entropy',
    "ts_ir",
    "ts_kurtosis",
    "ts_max",
    "ts_max_diff",
    "ts_mean",
    'ts_median',
    "ts_min",
    'ts_min_diff',
    'ts_min_max_cps',
    'ts_min_max_diff',
    "ts_product",
    "ts_quantile",
    "ts_rank",
    "ts_returns",
    "ts_scale",
    'ts_skewness',
    "ts_std_dev",
    "ts_sum",
    "ts_zscore",
]

VEC_OPS = [
    "vec_avg", 
    "vec_count",
    "vec_max", 
    "vec_min", 
    "vec_norm", 
    "vec_range",
    "vec_stddev",
    "vec_sum",
]

GROUP_OPS = [
    "group_count",  
    "group_max", 
    'group_median',
    "group_min", 
    "group_neutralize", 
    'group_normalize',
    "group_rank", 
    "group_scale", 
    "group_std_dev",
    "group_sum",
    "group_zscore"
]

OPS_SET = BASIC_OPS + TS_OPS
