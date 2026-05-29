"""
构建 MaxTradeOff → MaxTradeOn 的 Alpha 映射

原理：
    1. 获取 region 内所有 maxTrade=OFF 的原 Alpha（表达式 + ID）
    2. 对每个 MaxTradeOn 后的新 Alpha ID，调用 wqbs.locate_alpha() 获取表达式
    3. 比较表达式（regular.code），完全相同的建立映射
    4. 映射表保存到 data/maxtrade_mapping.json

运行方式:
    cd /home/worldquant/wqb/Code2.0
    /root/anaconda3/envs/worldquant/bin/python modules/competitions/Osmosis/v3/build_maxtrade_mapping.py

输出:
    - 终端打印映射关系
    - data/maxtrade_mapping_{region}_{timestamp}.json
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from wqbkit.modules.competitions.Osmosis.v3.osmosis_selector_v3 import OsmosisAlphaSelectorV3

OUTPUT_DIR = Path(__file__).parent / "data"


def build_mapping(
    region: str,
    new_alpha_ids: list,
    selector: OsmosisAlphaSelectorV3 = None,
    max_workers: int = 8,
):
    """
    构建 MaxTradeOff → MaxTradeOn 映射

    Args:
        region: 目标 region
        new_alpha_ids: MaxTradeOn 后的新 Alpha ID 列表
        selector: OsmosisAlphaSelectorV3 实例（可选）
        max_workers: 并发数

    Returns:
        list: [{"original_id": "...", "new_id": "...", "expression": "..."}, ...]
    """
    if selector is None:
        selector = OsmosisAlphaSelectorV3()

    print(f"\n{'='*60}")
    print(f"构建 {region} 的 MaxTrade 映射")
    print(f"{'='*60}")

    # 1. 获取该 region 所有 maxTrade=OFF 的原 Alpha
    print(f"\n[1/3] 获取 {region} 原 Alpha 池...")
    df = selector.fetch_candidates(
        region=region,
        type_filter="REGULAR",
        use_cache=True,
    )
    if df.empty:
        print(f"{region}: 无候选 Alpha")
        return []

    # 只保留 maxTrade=OFF 的
    df_off = df[df["max_trade"] == "OFF"].copy()
    if df_off.empty:
        print(f"{region}: 无 maxTrade=OFF 的 Alpha")
        return []

    print(f"  原 Alpha 池: {len(df)} 个 REGULAR")
    print(f"  maxTrade=OFF: {len(df_off)} 个")

    # 构建 (表达式, settings签名) → 原 Alpha ID 的映射
    # settings 签名用于区分表达式相同但参数不同的 Alpha
    SETTINGS_KEYS = [
        "region", "delay", "decay", "neutralization", "truncation",
        "pasteurization", "universe", "instrumentType"
    ]

    def make_settings_sig(settings):
        return tuple(settings.get(k) for k in SETTINGS_KEYS)

    sig_to_original = {}
    for _, row in df_off.iterrows():
        expr = row.get("expression", "").strip()
        settings = row.get("settings_full", {}) or row.get("settings", {})
        sig = make_settings_sig(settings)
        key = (expr, sig)
        if expr and key not in sig_to_original:
            sig_to_original[key] = row["id"]

    print(f"  唯一表达式: {len(set(k[0] for k in sig_to_original))} 个")
    print(f"  唯一(表达式+settings): {len(sig_to_original)} 个")

    # 2. 获取新 Alpha 的详细信息
    print(f"\n[2/3] 获取 {len(new_alpha_ids)} 个新 Alpha 的详细信息...")

    def fetch_new_alpha(alpha_id):
        try:
            resp = selector.wqbs.locate_alpha(alpha_id)
            data = resp.json()
            expr = data.get("regular", {}).get("code", "").strip()
            max_trade = data.get("settings", {}).get("maxTrade", "unknown")
            settings = data.get("settings", {})
            settings_sig = make_settings_sig(settings)
            return {
                "new_id": alpha_id,
                "expression": expr,
                "max_trade": max_trade,
                "settings_sig": settings_sig,
                "settings": {k: settings.get(k) for k in SETTINGS_KEYS},
                "status": "ok",
            }
        except Exception as e:
            return {
                "new_id": alpha_id,
                "expression": "",
                "max_trade": "unknown",
                "settings_sig": None,
                "settings": {},
                "status": f"error: {e}",
            }

    new_alphas = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {executor.submit(fetch_new_alpha, aid): aid for aid in new_alpha_ids}
        for future in tqdm(as_completed(future_to_id), total=len(new_alpha_ids), desc="locate_alpha"):
            result = future.result()
            new_alphas.append(result)

    # 3. 匹配表达式+settings建立映射
    print(f"\n[3/3] 匹配表达式+settings建立映射...")
    mapping = []
    unmatched = []

    for new_alpha in new_alphas:
        new_id = new_alpha["new_id"]
        expr = new_alpha["expression"]
        max_trade = new_alpha["max_trade"]
        sig = new_alpha["settings_sig"]

        if new_alpha["status"] != "ok":
            print(f"  ❌ {new_id}: 获取失败 ({new_alpha['status']})")
            unmatched.append({"new_id": new_id, "reason": "api_error"})
            continue

        if max_trade != "ON":
            print(f"  ⚠️  {new_id}: maxTrade={max_trade} (不是 ON)")
            unmatched.append({"new_id": new_id, "reason": f"maxTrade={max_trade}"})
            continue

        if not expr:
            print(f"  ⚠️  {new_id}: 无表达式")
            unmatched.append({"new_id": new_id, "reason": "no_expression"})
            continue

        original_id = sig_to_original.get((expr, sig))
        if original_id:
            mapping.append({
                "original_id": original_id,
                "new_id": new_id,
                "expression": expr[:200],
                "settings": new_alpha["settings"],
            })
            print(f"  ✅ {original_id} → {new_id}")
        else:
            # 尝试只匹配表达式，给出更详细的提示
            expr_only_matches = [oid for (e, s), oid in sig_to_original.items() if e == expr]
            if expr_only_matches:
                print(f"  ❌ {new_id}: 表达式匹配但 settings 不匹配 (表达式相同的有 {len(expr_only_matches)} 个原Alpha)")
                unmatched.append({"new_id": new_id, "reason": "settings_mismatch", "expression": expr[:200], "settings": new_alpha["settings"]})
            else:
                print(f"  ❌ {new_id}: 无匹配的原 Alpha (表达式未找到)")
                unmatched.append({"new_id": new_id, "reason": "no_match", "expression": expr[:200]})

    # 汇总
    print(f"\n{'='*60}")
    print("汇总")
    print(f"{'='*60}")
    print(f"  新 Alpha 总数: {len(new_alpha_ids)}")
    print(f"  成功映射: {len(mapping)}")
    print(f"  未匹配: {len(unmatched)}")

    if unmatched:
        print(f"\n  未匹配详情:")
        for u in unmatched:
            print(f"    {u['new_id']}: {u['reason']}")

    return mapping, unmatched


def apply_mapping_to_maxtrade_status(region: str, mapping: list, selector: OsmosisAlphaSelectorV3 = None):
    """
    将映射关系应用到 MaxTrade 映射表
    - 原 Alpha 标记为 has_maxTradeOn_sim=True
    - 记录 new_id 关联
    """
    if selector is None:
        selector = OsmosisAlphaSelectorV3()

    print(f"\n{'='*60}")
    print(f"更新 MaxTrade 映射表 ({len(mapping)} 条)")
    print(f"{'='*60}")

    for item in mapping:
        original_id = item["original_id"]
        new_id = item["new_id"]

        selector.update_maxtrade_status(
            alpha_id=original_id,
            has_maxTradeOn_sim=True,
            new_alpha_id=new_id,
            notes="MaxTradeOn simulation 完成",
        )

    print(f"✅ 已更新 {len(mapping)} 个原 Alpha 的 MaxTrade 状态")


if __name__ == "__main__":
    # IND MaxTradeOn 后的新 Alpha ID 列表
    IND_NEW_ALPHAS = [
        "zq5KAl3K", "YPNLlRxl", "6XRmG5Ap", "1YokGrjm", "Grn1QZO5",
        "3qEQG8Vz", "1YokGrZk", "pwnYW9Rj", "3qEQG8XZ", "le7pgo8l",
        "d5nk9bEX", "vR5wYrJG", "j2nzVAdj", "MPbMga58", "KPnlVNwj",
    ]

    selector = OsmosisAlphaSelectorV3()

    # 构建映射
    mapping, unmatched = build_mapping("IND", IND_NEW_ALPHAS, selector=selector)

    # 应用到 MaxTrade 映射表
    if mapping:
        apply_mapping_to_maxtrade_status("IND", mapping, selector=selector)
