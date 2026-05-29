import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

"""
Osmosis 分数清除模块

功能:
    1. 查找指定 region / 日期范围内已设置 osmosisPoints 的 Alpha
    2. 支持 dry_run 预览
    3. 支持并发清除
    4. 支持白名单保护（不清除指定 Alpha）

使用方式:
    from wqbkit.modules.competitions.Osmosis.v2_0.osmosis_clear import OsmosisClear

    clearer = OsmosisClear()

    # 预览（不实际清除）
    targets = clearer.scan(region="USA", dry_run=True)

    # 实际清除
    results = clearer.clear(region="USA")

    # 保护特定 Alpha
    results = clearer.clear(region="USA", protect_ids=["alpha_id_1"])
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from wqbkit.app.core.alpha_base_core import AlphaBaseCore

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.worldquantbrain.com"
ALPHAS_URL = f"{API_BASE_URL}/alphas"
USERS_SELF_URL = f"{API_BASE_URL}/users/self"

DEFAULT_BATCH_SIZE = 100
DEFAULT_ALPHA_LIMIT = 2000
MAX_WORKERS = 10


class OsmosisClear(AlphaBaseCore):
    """Osmosis 分数清除器"""

    def __init__(self):
        super().__init__()
        self.logger.info("OsmosisClear initialized")

    def scan(
        self,
        region: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        type_filter: Optional[str] = None,
        dry_run: bool = False,
    ) -> List[Dict]:
        """
        扫描已设置 osmosisPoints 的 Alpha

        Args:
            region: 目标 region，None 表示所有 region
            start_date: 提交日期下限 (YYYY-MM-DD)
            end_date: 提交日期上限 (YYYY-MM-DD)
            type_filter: Alpha 类型过滤 (REGULAR / SUPER)
            dry_run: 若为 True，只扫描不返回详细日志

        Returns:
            已设置分数的 Alpha 列表 [{"id": ..., "osmosisPoints": ..., "region": ...}]
        """
        if start_date is None:
            start_date = "2025-01-01"
        if end_date is None:
            end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        targets = []

        for offset in range(0, DEFAULT_ALPHA_LIMIT, DEFAULT_BATCH_SIZE):
            url = (
                f"{USERS_SELF_URL}/alphas?"
                f"limit={DEFAULT_BATCH_SIZE}&offset={offset}"
                f"&status!=UNSUBMITTED&status!=IS_FAIL"
                f"&hidden=false"
                f"&dateSubmitted>={start_date}T00:00:00-04:00"
                f"&dateSubmitted<{end_date}T00:00:00-04:00"
            )
            if region:
                url += f"&settings.region={region}"
            if type_filter:
                url += f"&type={type_filter}"

            try:
                resp = self.get(url)
                resp.raise_for_status()
                results = resp.json().get("results", [])

                if not results:
                    break

                for alpha in results:
                    if alpha.get("osmosisPoints") is not None:
                        targets.append({
                            "id": alpha["id"],
                            "osmosisPoints": alpha["osmosisPoints"],
                            "region": alpha.get("settings", {}).get("region", "unknown"),
                            "type": alpha.get("type", "unknown"),
                        })
            except Exception as e:
                self.logger.error(f"扫描异常: {e}")
                break

        if not dry_run:
            self.logger.info(f"扫描完成: 找到 {len(targets)} 个已设置分数的 Alpha")
        return targets

    def clear_one(self, alpha_id: str, old_points) -> str:
        """清除单个 Alpha 的 osmosisPoints"""
        try:
            resp = self.patch(f"{ALPHAS_URL}/{alpha_id}", json={"osmosisPoints": None})
            if resp.status_code == 200:
                self.logger.info(f"✓ 清除 {alpha_id} (原分数: {old_points})")
                return "SUCCESS"
            else:
                self.logger.error(f"✗ 清除 {alpha_id} 失败: HTTP {resp.status_code}")
                return "FAILED"
        except Exception as e:
            self.logger.error(f"✗ 清除 {alpha_id} 异常: {e}")
            return "FAILED"

    def clear(
        self,
        region: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        type_filter: Optional[str] = None,
        protect_ids: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """
        批量清除 osmosisPoints

        Args:
            region: 目标 region
            start_date / end_date: 日期范围
            type_filter: 类型过滤
            protect_ids: 保护列表中的 Alpha 不被清除
            dry_run: 若为 True，只打印不实际清除

        Returns:
            {"success": n, "failed": n, "protected": n}
        """
        targets = self.scan(region, start_date, end_date, type_filter)

        if not targets:
            self.logger.info("没有需要清除的 Alpha")
            return {"success": 0, "failed": 0, "protected": 0}

        protect_set = set(protect_ids or [])
        to_clear = [t for t in targets if t["id"] not in protect_set]
        protected = [t for t in targets if t["id"] in protect_set]

        self.logger.info(f"待清除: {len(to_clear)} 个 | 受保护: {len(protected)} 个")

        if dry_run:
            for t in to_clear:
                self.logger.info(f"[DRY RUN] 将清除 {t['id']} (region={t['region']}, type={t['type']}, points={t['osmosisPoints']})")
            return {"success": 0, "failed": 0, "protected": len(protected), "dry_run": len(to_clear)}

        # 并发清除
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(self.clear_one, t["id"], t["osmosisPoints"]): t
                for t in to_clear
            }
            for future in futures:
                results.append(future.result())

        success = results.count("SUCCESS")
        failed = results.count("FAILED")

        self.logger.info(f"清除完成: 成功 {success} | 失败 {failed} | 保护 {len(protected)}")
        return {"success": success, "failed": failed, "protected": len(protected)}


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Osmosis 分数清除工具")
    parser.add_argument("--region", default=None, help="目标 region")
    parser.add_argument("--start", default="2025-01-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--type", default=None, choices=["REGULAR", "SUPER"], help="Alpha 类型")
    parser.add_argument("--dry-run", action="store_true", help="只预览不清除")
    parser.add_argument("--scan-only", action="store_true", help="只扫描不操作")
    args = parser.parse_args()

    clearer = OsmosisClear()

    if args.scan_only or args.dry_run:
        targets = clearer.scan(
            region=args.region,
            start_date=args.start,
            end_date=args.end,
            type_filter=args.type,
            dry_run=args.dry_run,
        )
        print(f"\n找到 {len(targets)} 个已设置分数的 Alpha:")
        for t in targets:
            print(f"  {t['id']} | {t['region']} | {t['type']} | points={t['osmosisPoints']}")
    else:
        results = clearer.clear(
            region=args.region,
            start_date=args.start,
            end_date=args.end,
            type_filter=args.type,
            dry_run=args.dry_run,
        )
        print(f"\n结果: {results}")


if __name__ == "__main__":
    main()
