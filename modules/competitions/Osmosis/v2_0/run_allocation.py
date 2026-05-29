import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

"""
Osmosis 多 Region 批量分配脚本

运行方式:
    cd /home/worldquant/wqb/Code2.0
    python -m modules.competitions.Osmosis.v2_0.run_allocation

逻辑:
    1. 遍历 USA / GLB / EUR / ASI / IND
    2. 对每个 region 执行粗筛 + score_prop(t=0.15) 分配
    3. 仅当选出 >= 10 个 Alpha 时才输出分配结果
    4. 不调用 API 写入（纯输出预览）
"""

import logging
from datetime import datetime

import pandas as pd

from wqbkit.modules.competitions.Osmosis.v2_0.osmosis_selector import OsmosisAlphaSelector
from wqbkit.modules.competitions.Osmosis.v2_0.osmosis_allocator import OsmosisAllocator
from wqbkit.modules.competitions.Osmosis.v2_0.osmosis_clear import OsmosisClear

# 配置
REGIONS = ["USA", "GLB", "EUR", "ASI", "IND"]
START_DATE = datetime(2025, 4, 19)
MIN_ALPHA_COUNT = 10
TOTAL_SCORE = 100000


def print_region_result(region: str, df: pd.DataFrame):
    """打印单个 region 的分配结果"""
    print()
    print("=" * 80)
    print(f"【{region}】分配结果: {len(df)} 个 Alpha, 总分={df['assigned_score'].sum()}")
    print("=" * 80)

    # 按分数降序
    df = df.sort_values("assigned_score", ascending=False).reset_index(drop=True)

    # 基础统计
    print(f"  最高: {df['assigned_score'].max():,.0f}  |  最低: {df['assigned_score'].min():,.0f}  |  中位数: {df['assigned_score'].median():,.0f}")

    # SuperAlpha / REGULAR 分布
    super_count = (df["type"] == "SUPER").sum() if "type" in df.columns else 0
    regular_count = len(df) - super_count
    print(f"  SuperAlpha: {super_count}  |  REGULAR: {regular_count}")
    print()

    # Top 15 详情
    display_cols = ["id", "type", "sharpe", "fitness", "turnover", "assigned_score"]
    available_cols = [c for c in display_cols if c in df.columns]
    print(df[available_cols].head(15).to_string(index=False))
    print()

    # 分数分布
    bins = [0, 500, 1000, 2000, 5000, 10000, 20000, 100000]
    labels = ["<500", "500-1k", "1-2k", "2-5k", "5-10k", "10-20k", ">20k"]
    df["bin"] = pd.cut(df["assigned_score"], bins=bins, labels=labels)
    print("  分数分布:")
    print("  " + df["bin"].value_counts().sort_index().to_string().replace("\n", "\n  "))
    print()


def run(update: bool = False):
    """
    执行多 Region 批量分配

    Args:
        update: 若为 True，先 clear 旧分数再写入新分数
    """
    print("=" * 80)
    print("Osmosis 多 Region 批量分配")
    print("=" * 80)
    print(f"Regions: {REGIONS}")
    print(f"Start Date: {START_DATE.date()}")
    print(f"Min Alpha Count: {MIN_ALPHA_COUNT}")
    print(f"分配方法: score_prop (temperature=0.15)")
    print(f"API 写入: {'启用（先 clear 再 update）' if update else '禁用'}")
    print()

    print("[初始化] 加载组件...")
    selector = OsmosisAlphaSelector()
    allocator = OsmosisAllocator()
    clearer = OsmosisClear() if update else None
    print("[初始化] 完成\n")

    results_summary = []
    failed_alphas = []  # 收集所有更新失败的 Alpha

    for region in REGIONS:
        print(f"\n{'>'*40} {region} {'<'*40}")

        # 1. 粗筛
        try:
            df_selected = selector.select(region=region, start_date=START_DATE)
        except Exception as e:
            print(f"【{region}】粗筛异常: {e}")
            continue

        if df_selected.empty or len(df_selected) < MIN_ALPHA_COUNT:
            print(f"【{region}】仅 {len(df_selected)} 个 Alpha，不足 {MIN_ALPHA_COUNT}，跳过")
            results_summary.append({"region": region, "status": "跳过", "count": len(df_selected), "total": 0})
            continue

        # 2. 分配
        try:
            df_alloc = allocator.allocate(
                df_selected,
                method="score_prop",
                total_score=TOTAL_SCORE,
                temperature=0.15,
            )
        except Exception as e:
            print(f"【{region}】分配异常: {e}")
            continue

        # 3. 输出结果
        print_region_result(region, df_alloc)

        # 4. 可选：清除 + 写入
        if update and clearer:
            print(f"  [{region}] 清除旧分数...")
            clear_result = clearer.clear(region=region)
            print(f"  [{region}] 清除完成: {clear_result}")

            print(f"  [{region}] 写入新分数...")
            update_result = allocator.update_osmosis_points(df_alloc)
            success = len([s for s in update_result.values() if s == 200])
            failed = [aid for aid, code in update_result.items() if code != 200]
            failed_alphas.extend(failed)
            print(f"  [{region}] 写入完成: {success}/{len(update_result)} 成功")
            if failed:
                print(f"  [{region}] 失败: {failed}")

        results_summary.append({
            "region": region,
            "status": "成功",
            "count": len(df_alloc),
            "total": int(df_alloc["assigned_score"].sum()),
            "super": int((df_alloc["type"] == "SUPER").sum()) if "type" in df_alloc.columns else 0,
            "regular": int((df_alloc["type"] != "SUPER").sum()) if "type" in df_alloc.columns else len(df_alloc),
            "max": int(df_alloc["assigned_score"].max()),
            "min": int(df_alloc["assigned_score"].min()),
        })

    # 总览表
    print()
    print("=" * 80)
    print("总览")
    print("=" * 80)
    df_summary = pd.DataFrame(results_summary)
    print(df_summary.to_string(index=False))
    print()
    # 显示所有更新失败的 Alpha
    if failed_alphas:
        print()
        print("=" * 80)
        print(f"⚠️ 更新失败的 Alpha ({len(failed_alphas)} 个)")
        print("=" * 80)
        for aid in failed_alphas:
            print(f"  {aid}")
    else:
        print()
        print("✅ 所有 Alpha 更新成功")

    print()
    print("运行完成")


if __name__ == "__main__":
    # 设置参数
    UPDATE = False  # 设为 True 则启用先 clear 再 update
    run(update=UPDATE)
