import re
from typing import List, Optional, Tuple

def extract_tokens(
    alpha: str,
    operators: List[str],
    sep: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    """
    从 alpha 表达式中提取使用的算子和数据字段。
    
    Args:
        alpha: Alpha 表达式字符串
        operators: 常规算子列表
        sep: 需要排除的特定字符串列表
        
    Returns:
        (operators_used, data_fields_used): 使用的算子列表和数据字段列表
    """
    if sep is None:
        sep = []
        
    tokens = set(re.findall(r"[a-zA-Z0-9_.]+", alpha))
    
    operators_set = set(operators)
    sep_set = set(sep)
    
    operators_used = [f for f in tokens if f in operators_set]
    data_fields_used = sorted([
        f for f in [f for f in tokens if f not in operators_set]
        if not f.isdigit() and len(f) >= 4 and f not in sep_set
    ])
    
    return operators_used, data_fields_used

