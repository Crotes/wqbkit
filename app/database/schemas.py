"""
Alpha 相关数据结构的数据类。
为了解决循环依赖问题，从 app.core.alpha_dataclass 移动至此。
"""
from dataclasses import astuple, dataclass
from typing import Iterator, Optional


@dataclass(slots=True)
class FactorData:
    """Alpha Factor 数据结构。"""
    factor_id: Optional[int]
    pre: str
    expression: str
    neutralization: str
    region: str
    universe: str
    decay: int
    task_id: Optional[int]
    priority: int
    generation: int
    tag: str

    def __iter__(self) -> Iterator:
        return iter(astuple(self))


@dataclass(slots=True)
class SimulationData:
    """Simulation 数据结构。"""
    alpha_id: str

    expression: str
    region: str
    universe: str
    neutralization: str
    decay: int
    delay: int

    sharpe: float
    fitness: float
    drawdown: float
    twoyearsharpe: float

    fail_num: int

    pre: str = ""
    priority: int = 0
    score: float = 0.0
    task_id: Optional[int] = None
    generation: int = 0
    tag: str = ""

    def __iter__(self) -> Iterator:
        return iter(astuple(self))


@dataclass(slots=True)
class TaskData:
    """Task 数据结构。"""
    pre: str
    name: str
    region: str
    universe: str
    neutralization: str
    decay: int
    generation: int
    priority: int
    parent_task_id: Optional[int]
    total_alphas: int
    tag: str
    task_id: Optional[int] = None

    def __iter__(self) -> Iterator:
        return iter(astuple(self))

@dataclass(slots=True)
class FieldDate:
    """Field 数据结构。"""
    id: str
    description: str
    dataset_id: str
    dataset_name: str
    category_id: str
    category_name: str
    subcategory_id: str
    subcategory_name: str
    region: str
    delay: int
    universe:str 
    type: str
    coverage: float
    usercount: int
    alphacount: int
    themes: str
    researchpapers: str