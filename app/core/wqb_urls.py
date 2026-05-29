"""
WorldQuant Brain API URL 定义
此文件包含用于与 WorldQuant Brain API 交互的 URL 常量。
它与 `wqb` 库定义对齐，并包含项目特定的扩展。
"""

# 基础 URL
HOST = "https://api.worldquantbrain.com"
WQB_API_URL = HOST

# -----------------------------------------------------------------------------
# 官方 wqb 库常量
# -----------------------------------------------------------------------------
URL_AUTHENTICATION = WQB_API_URL + '/authentication'

URL_USERS = WQB_API_URL + '/users'
URL_USERS_SELF = URL_USERS + '/self'
URL_USERS_SELF_ALPHAS = URL_USERS_SELF + '/alphas'

URL_DATACATEGORIES = WQB_API_URL + '/data-categories'

URL_DATAFIELDS = WQB_API_URL + '/data-fields'
URL_DATAFIELDS_FIELDID = URL_DATAFIELDS + '/{}'

URL_DATASETS = WQB_API_URL + '/data-sets'
URL_DATASETS_DATASETID = URL_DATASETS + '/{}'

URL_OPERATORS = WQB_API_URL + '/operators'

URL_SIMULATIONS = WQB_API_URL + '/simulations'

URL_ALPHAS = WQB_API_URL + '/alphas'
URL_ALPHAS_ALPHAID = URL_ALPHAS + '/{}'
URL_ALPHAS_ALPHAID_CHECK = URL_ALPHAS_ALPHAID + '/check'
# 注意：官方库明确使用 http 和端口 443 进行提交
URL_ALPHAS_ALPHAID_SUBMIT = 'http://api.worldquantbrain.com:443/alphas/{}/submit'

# -----------------------------------------------------------------------------
# 项目特定扩展（不在官方 wqb 库中）
# -----------------------------------------------------------------------------
# 用于 alpha_machine.py 和 alpha_calc_corr.py
URL_ALPHA_PNL = URL_ALPHAS_ALPHAID + "/recordsets/pnl"
