"""
提取 maxTrade=OFF 且未做 MaxTradeOn simulation 的 Alpha ID

运行方式:
    cd /home/worldquant/wqb/Code2.0
    /root/anaconda3/envs/worldquant/bin/python modules/competitions/Osmosis/v3/extract_maxtrade_off.py

输出:
    - 终端打印 Alpha ID 列表（按 region 分组）
    - 保存到 data/maxtrade_off_pending.json
    - 可选保存为纯文本列表（方便粘贴到 WQB 批量操作）

手动操作流程:
    1. 运行此脚本获取 Alpha ID 列表
    2. 在 WQB 平台上逐个/批量对这些 Alpha 重新 simulation（启用 MaxTradeOn）
    3. 记录 simulation 结果（sharpe, fitness 等）
    4. 调用 selector.update_maxtrade_status(alpha_id, has_maxTradeOn_sim=True, ...) 更新映射表
    5. 重新运行 selector.select() 获取更新后的候选池
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from wqbkit.modules.competitions.Osmosis.v3.osmosis_selector_v3 import OsmosisAlphaSelectorV3

# 配置
REGIONS = ["USA", "GLB", "EUR", "ASI", "IND"]
START_DATE = datetime(2025, 4, 19)
OUTPUT_DIR = Path(__file__).parent / "data"


def extract_maxtrade_off(
    regions=None,
    start_date=START_DATE,
    save_json=True,
    save_txt=True,
    print_detail=True,
):
    """
    提取所有 maxTrade=OFF 且未做 MaxTradeOn simulation 的 Alpha

    Args:
        regions: region 列表，默认 REGIONS
        start_date: 创建日期下限
        save_json: 是否保存 JSON 文件
        save_txt: 是否保存纯文本 ID 列表
        print_detail: 是否打印详细信息

    Returns:
        dict: {region: [alpha_info, ...]}
    """
    regions = regions or REGIONS
    selector = OsmosisAlphaSelectorV3()

    all_pending = {}
    total_count = 0

    print("=" * 80)
    print("MaxTrade=OFF 待处理 Alpha 提取")
    print("=" * 80)
    print(f"Regions: {regions}")
    print(f"Start Date: {start_date.date()}")
    print()

    for region in regions:
        print(f"\n{'>'*40} {region} {'<'*40}")

        # 获取候选（只取 REGULAR，SuperAlpha 不涉及 maxTrade）
        try:
            df = selector.fetch_candidates(
                region=region,
                start_date=start_date,
                type_filter="REGULAR",
                use_cache=True,
            )
        except Exception as e:
            print(f"获取 {region} 候选失败: {e}")
            continue

        if df.empty:
            print(f"{region}: 无候选 Alpha")
            continue

        # 筛选 maxTrade=OFF
        df_off = df[df["max_trade"] == "OFF"].copy()
        if df_off.empty:
            print(f"{region}: 无 maxTrade=OFF 的 Alpha")
            continue

        # 筛选尚未做 MaxTradeOn simulation 的
        pending = []
        for _, row in df_off.iterrows():
            status = selector.get_maxtrade_status(row["id"])
            if not status.get("has_maxTradeOn_sim", False):
                pending.append({
                    "id": row["id"],
                    "sharpe": row.get("sharpe"),
                    "fitness": row.get("fitness"),
                    "turnover": row.get("turnover"),
                    "returns": row.get("returns"),
                    "drawdown": row.get("drawdown"),
                    "margin": row.get("margin"),
                    "dataset_tag": row.get("dataset_tag", "unknown"),
                    "neutralization": row.get("neutralization", "unknown"),
                    "expression": row.get("expression", "")[:80],
                    "settings_full": row.get("settings_full", {}),
                    "regular_full": row.get("regular_full", {}),
                })

        if not pending:
            print(f"{region}: {len(df_off)} 个 maxTrade=OFF，但全部已有 MaxTradeOn 记录")
            continue

        all_pending[region] = pending
        total_count += len(pending)

        print(f"{region}: {len(df)} 个 REGULAR 候选")
        print(f"       maxTrade=OFF: {len(df_off)} 个")
        print(f"       待处理（无 MaxTradeOn sim）: {len(pending)} 个")

        if print_detail:
            # 按 dataset_tag 分组统计
            df_pending = pd.DataFrame(pending)
            print(f"\n  按 dataset_tag 分布:")
            for tag, count in df_pending["dataset_tag"].value_counts().items():
                print(f"    {tag}: {count} 个")

            # 打印 Top 10（按 sharpe 排序）
            print(f"\n  Top 10 待处理 Alpha（按 sharpe）:")
            top10 = df_pending.nlargest(10, "sharpe")[["id", "sharpe", "fitness", "turnover", "dataset_tag"]]
            print("  " + top10.to_string(index=False).replace("\n", "\n  "))

            # 打印所有 ID（方便复制）
            print(f"\n  所有待处理 ID:")
            ids_str = ", ".join([p["id"] for p in pending])
            # 每 5 个换行，方便阅读
            ids_lines = [pending[i:i+5] for i in range(0, len(pending), 5)]
            for line in ids_lines:
                print("    " + ", ".join([p["id"] for p in line]))

    # 汇总
    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)
    for region, pending in all_pending.items():
        print(f"  {region}: {len(pending)} 个待处理")
    print(f"\n  总计: {total_count} 个 Alpha 需要 MaxTradeOn simulation")
    print()

    # 保存文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if save_json and all_pending:
        json_path = OUTPUT_DIR / f"maxtrade_off_pending_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(),
                    "total": total_count,
                    "regions": all_pending,
                },
                f, indent=2, ensure_ascii=False,
            )
        print(f"JSON 已保存: {json_path}")

    if save_txt and all_pending:
        txt_path = OUTPUT_DIR / f"maxtrade_off_pending_{timestamp}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            for region, pending in all_pending.items():
                f.write(f"# {region} ({len(pending)} 个)\n")
                for p in pending:
                    f.write(f"{p['id']}\n")
                f.write("\n")
        print(f"TXT 已保存: {txt_path}")

    # 导出 simulation 请求体（按 region 分开，每个 region 一个 JSON 文件）
    if all_pending:
        for region, pending in all_pending.items():
            region_requests = []
            for p in pending:
                settings = dict(p.get("settings_full", {}))
                # 关键：把 maxTrade 改为 ON
                settings["maxTrade"] = "ON"
                region_requests.append({
                    "type": "REGULAR",
                    "settings": settings,
                    "regular": p.get("regular_full", {}).get("code", ""),
                })

            sim_path = OUTPUT_DIR / f"maxtrade_sim_requests_{region}_{timestamp}.json"
            with open(sim_path, "w", encoding="utf-8") as f:
                json.dump(region_requests, f, indent=2, ensure_ascii=False)
            print(f"Simulation 请求体已保存: {sim_path} ({len(region_requests)} 个)")

    return all_pending


def print_update_template(all_pending):
    """
    打印 update_maxtrade_status 的代码模板，方便用户批量更新
    """
    print("\n" + "=" * 80)
    print("更新模板（完成 simulation 后使用）")
    print("=" * 80)
    print("""
# 在完成 MaxTradeOn simulation 后，批量更新映射表：
from wqbkit.modules.competitions.Osmosis.v3.osmosis_selector_v3 import OsmosisAlphaSelectorV3
selector = OsmosisAlphaSelectorV3()

# 逐个更新（或循环批量更新）
""")
    for region, pending in all_pending.items():
        print(f"# {region} ({len(pending)} 个)")
        for p in pending[:3]:  # 只显示前 3 个作为示例
            print(f"""selector.update_maxtrade_status(
    alpha_id="{p['id']}",
    has_maxTradeOn_sim=True,
    maxTradeOn_sharpe=...,  # 填入 MaxTradeOn 后的 sharpe
    maxTradeOn_fitness=..., # 填入 MaxTradeOn 后的 fitness
)""")
        if len(pending) > 3:
            print(f"# ... 还有 {len(pending) - 3} 个")
        print()


if __name__ == "__main__":
    pending = extract_maxtrade_off(
        regions=REGIONS,
        start_date=START_DATE,
        save_json=True,
        save_txt=True,
        print_detail=True,
    )

    if pending:
        print_update_template(pending)
    else:
        print("\n✅ 所有 Alpha 都已通过 MaxTradeOn 验证！")
