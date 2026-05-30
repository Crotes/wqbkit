from itertools import product
from typing import List

import pandas as pd

from wqbkit.modules.regular_alpha.alpha_machine.config.operators import (
    TS_OPS, VEC_OPS, GROUP_OPS
)
from wqbkit.modules.regular_alpha.alpha_machine.config.constants import (
    TS_DAYS, TS_COMP_DAYS, VECTORS, ZERO_ORDER_NUM_OP, ZERO_ORDER_BASE_OP
)
from wqbkit.modules.regular_alpha.alpha_machine.config.groups import PV_GROUPS, ATOM_GROUPS, FUNDAMENTAL_GROUPS
from wqbkit.modules.regular_alpha.alpha_machine.config.events import OPEN_EVENTS, EXIT_EVENTS


DEFAULT_BACKFILL_WINDOW = 120
DEFAULT_ZSCORE_WINDOW = 250
GROUP_PERCENTAGE = 0.5


class AlphaGenerator:

    def get_vec_fields(self, fields: List[str]) -> List[str]:
        """为 VECTOR 类型字段添加 vec 算子前缀。"""
        vec_fields = []
        for field in fields:
            for vec_op in VEC_OPS:
                if vec_op == "vec_choose":
                    vec_fields.append("%s(%s, nth=-1)" % (vec_op, field))
                    vec_fields.append("%s(%s, nth=0)" % (vec_op, field))
                else:
                    vec_fields.append("%s(%s)" % (vec_op, field))
        return vec_fields

    def process_datafields(self, df: pd.DataFrame) -> List[str]:
        """将 DataFrame 中的 MATRIX/VECTOR 字段转换为带 backfill 的表达式列表。"""
        datafields = []
        datafields += df[df["type"] == "MATRIX"]["id"].tolist()
        datafields += self.get_vec_fields(df[df["type"] == "VECTOR"]["id"].tolist())
        return [f"ts_backfill({field}, {DEFAULT_BACKFILL_WINDOW})" for field in datafields]

    def ts_factory(self, op: str, field: str) -> List[str]:
        """时间序列算子工厂：按 TS_DAYS 生成多个时间窗口的表达式。"""
        output = []
        if op == 'ts_target_tvr_decay' or op == 'ts_target_tvr_hump':
            alpha = "%s(%s, lambda_min=0, lambda_max=1, target_tvr=0.1)" % (op, field) 
        else:
            for day in TS_DAYS:
                if op == 'jump_decay':
                    alpha = "%s(%s, %d, stddev=True, sensitivity=0.5, force=0.1)" % (op, field, day) 
                else:
                    alpha = "%s(%s, %d)" % (op, field, day) 
                output.append(alpha)
        return output

    def vector_factory(self, op: str, field: str) -> List[str]:
        """向量算子工厂：按 VECTORS 生成多个向量维度的表达式。"""
        output = []
        for vector in VECTORS:
            alpha = "%s(%s, %s)" % (op, field, vector)
            output.append(alpha)
        return output

    def ts_comp_factory(self, op: str, field: str, factor: str, paras: List) -> List[str]:
        """带参数的 TS 算子工厂：笛卡尔积生成 (day, para) 组合表达式。"""
        output = []
        l2 = paras
        comb = list(product(TS_COMP_DAYS, l2))

        for day, para in comb:
            if isinstance(para, float):
                alpha = "%s(%s, %d, %s=%.1f)" % (op, field, day, factor, para)
            elif isinstance(para, int):
                alpha = "%s(%s, %d, %s=%d)" % (op, field, day, factor, para)
            output.append(alpha)
        return output

    def group_factory(self, op: str, field: str, region: str, atom: bool, fundamental: bool, pv: bool) -> List[str]:
        """Group 算子工厂：按 region 和分类开关生成 group 表达式。"""
        output = []
        groups = []

        if atom:
            groups += ATOM_GROUPS

        if pv:
            groups += PV_GROUPS["COMMON"]
            if region in PV_GROUPS:
                groups += PV_GROUPS[region]
            
        if fundamental:
            groups += FUNDAMENTAL_GROUPS["COMMON"]
            if region in FUNDAMENTAL_GROUPS:
                groups += FUNDAMENTAL_GROUPS[region]

        for group in groups:
            if op.startswith("group_vector"):
                for vector in VECTORS:
                    alpha = "%s(%s,%s,densify(%s))" % (op, field, vector, group)
                    output.append(alpha)
            elif op.startswith("group_percentage"):
                alpha = "%s(%s,densify(%s),percentage=%s)" % (op, field, group, GROUP_PERCENTAGE)
                output.append(alpha)
            else:
                alpha = "%s(%s,%s)" % (op, field, group)
                output.append(alpha)

        return output

    def zero_order_factory(self, fields: str) -> List[str]:
        """零阶表达式工厂：基础数值/排名变换组合。"""
        expression = []
        for op1 in ZERO_ORDER_NUM_OP:
            if op1 == '':
                expr1 = fields
            else:
                expr1 = f"{op1}({fields})"
            for op in ZERO_ORDER_BASE_OP:
                if op == '':
                    expression.append(f"{expr1}")
                else:
                    expression.append(f"{op}({expr1})")
            expression.append(f"rank({expr1}-ts_zscore({expr1},{DEFAULT_ZSCORE_WINDOW}))")
        
        return expression

    def first_order_factory(self, base: str) -> List[str]:
        """一阶表达式工厂：对基础表达式应用所有 TS 算子。"""
        alpha_set = []
        for op in TS_OPS:
            alpha_set.extend(self.ts_factory(op, base))
        return alpha_set

    def second_order_factory(self, first_order: str, region: str, atom: bool, fundamental: bool, pv: bool) -> List[str]:
        """二阶表达式工厂：对一阶结果应用所有 Group 算子。"""
        second_order = []
        for group_op in GROUP_OPS:
            second_order.extend(self.group_factory(group_op, first_order, region, atom, fundamental, pv))
        return second_order

    def third_order_factory(self, op: str, field: str, region: str) -> List[str]:
        """三阶表达式工厂：事件驱动型表达式组合（open/exit）。"""
        output = []
        for oe in OPEN_EVENTS:
            for ee in EXIT_EVENTS:
                alpha = "%s(%s, %s, %s)" % (op, oe, field, ee)
                output.append(alpha)
        return output
