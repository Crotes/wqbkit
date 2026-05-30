import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from wqbkit.app.config import config
from wqbkit.modules.competitions.Osmosis.osmosis_allocator_v3 import OsmosisAllocatorV3
from wqbkit.modules.competitions.Osmosis.osmosis_clear_v3 import OsmosisClearV3
from wqbkit.modules.competitions.Osmosis.osmosis_selector_v3 import OsmosisAlphaSelectorV3



class OsmosisRunnerV3:
    """
    Osmosis V3 端到端运行器

    串联 Selector → Allocator → Clear → API Update 的完整流水线。
    原型继承自 V2 run_allocation.py，V3 增强：
    - Config 驱动（region / method / constraints 全部可配）
    - 分数分布报表（继承 V1 oss2.py）
    - dry_run 模式（全程只打印不操作）
    - 异常隔离（单个 region 失败不影响其他 region）

    使用方式:
        runner = OsmosisRunnerV3()
        runner.run(update=False, dry_run=True)   # 预览
        runner.run(update=True, dry_run=False)   # 正式执行（先 clear 再 update）
    """

    DEFAULT_CONFIG = {
        # --- Region & Pipeline ---
        "regions": ["USA", "GLB", "EUR", "ASI", "IND"],
        "start_date": "2025-04-19",
        "min_alpha_count": 10,
        "total_score": config.TOTAL_SCORE,

        # --- Allocation ---
        "allocation_method": "mixed",
        "apply_constraints": True,

        # --- Reporting ---
        "score_bins": [0, 500, 1000, 2000, 5000, 10000, 20000, 100000],
        "score_bin_labels": ["<500", "500-1k", "1-2k", "2-5k", "5-10k", "10-20k", ">20k"],
    }

    def __init__(
        self,
        config: Optional[Dict] = None,
        selector_config: Optional[Dict] = None,
        allocator_config: Optional[Dict] = None,
        clear_config: Optional[Dict] = None,
    ):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self.selector = OsmosisAlphaSelectorV3(config=selector_config)
        self.allocator = OsmosisAllocatorV3(config=allocator_config)
        self.clearer = OsmosisClearV3(config=clear_config)
        self.logger = logging.getLogger(__name__)
        self.logger.info("OsmosisRunnerV3 initialized")

    # ==================================================================
    # 主入口
    # ==================================================================
    def run(self, update: bool = False) -> List[Dict]:
        """
        执行多 Region 完整流水线

        Args:
            update: 若为 True，执行完整流程（clear 旧分数 → 写入新分数）；
                    若为 False（默认），仅运行 select + allocate + report，不操作 API。

        Returns:
            每个 region 的结果摘要列表
        """
        cfg = self.config
        regions = cfg["regions"]
        start_date = datetime.strptime(cfg["start_date"], "%Y-%m-%d")

        self._print_header(regions, start_date, update)

        results_summary = []
        all_failed_alphas = []

        for region in regions:
            region_result = self._run_region(region, start_date, update)
            results_summary.append(region_result)
            all_failed_alphas.extend(region_result.get("failed_alphas", []))

        self._print_summary(results_summary)

        if all_failed_alphas:
            self._print_failed_alphas(all_failed_alphas)
        elif update:
            self.logger.info("✅ 所有 Alpha 更新成功")

        return results_summary

    def _run_region(
        self,
        region: str,
        start_date: datetime,
        update: bool,
    ) -> Dict:
        """执行单个 region 的流水线"""
        cfg = self.config
        min_alpha_count = cfg["min_alpha_count"]
        total_score = cfg["total_score"]
        method = cfg["allocation_method"]
        apply_constraints = cfg["apply_constraints"]

        self.logger.info(f"{'='*40} {region} {'='*40}")

        # --- Step 1: Selector ---
        try:
            df_selected = self.selector.select(region=region, start_date=start_date)
        except Exception as e:
            self.logger.error(f"【{region}】Selector 异常: {e}")
            return self._make_region_result(region, "Selector异常", 0, 0, [])

        if df_selected.empty or len(df_selected) < min_alpha_count:
            self.logger.warning(
                f"【{region}】仅 {len(df_selected)} 个 Alpha，不足 {min_alpha_count}，跳过"
            )
            return self._make_region_result(region, "跳过", len(df_selected), 0, [])

        # --- Step 2: Allocator ---
        try:
            df_alloc = self.allocator.allocate(
                df_selected,
                method=method,
                total_score=total_score,
                apply_constraints=apply_constraints,
            )
        except Exception as e:
            self.logger.error(f"【{region}】Allocator 异常: {e}")
            return self._make_region_result(region, "Allocator异常", len(df_selected), 0, [])

        # --- Step 3: Report ---
        self._print_region_report(region, df_alloc)

        # --- Step 4: Clear + Update (仅在 update=True 时执行) ---
        failed_alphas = []
        if update:
            # Clear
            try:
                self.logger.info(f"  [{region}] 清除旧分数...")
                clear_result = self.clearer.clear(region=region)
                self.logger.info(f"  [{region}] 清除完成: {clear_result}")
            except Exception as e:
                self.logger.error(f"  [{region}] 清除异常: {e}")

            # Update
            try:
                self.logger.info(f"  [{region}] 写入新分数...")
                update_result = self.allocator.update_osmosis_points(df_alloc, dry_run=False)
                success = sum(1 for code in update_result.values() if code == 200)
                failed = [aid for aid, code in update_result.items() if code != 200]
                failed_alphas.extend(failed)
                self.logger.info(f"  [{region}] 写入完成: {success}/{len(update_result)} 成功")
                if failed:
                    self.logger.warning(f"  [{region}] 失败: {failed}")
            except Exception as e:
                self.logger.error(f"  [{region}] 写入异常: {e}")

        return self._make_region_result(
            region=region,
            status="成功",
            count=len(df_alloc),
            total=int(df_alloc["assigned_score"].sum()),
            failed_alphas=failed_alphas,
            max_score=int(df_alloc["assigned_score"].max()),
            min_score=int(df_alloc["assigned_score"].min()),
            super_count=int((df_alloc["type"] == "SUPER").sum()) if "type" in df_alloc.columns else 0,
        )

    # ==================================================================
    # 报表输出
    # ==================================================================
    def _print_header(self, regions, start_date, update):
        """打印运行头信息"""
        self.logger.info("=" * 80)
        self.logger.info("Osmosis V3 多 Region 批量分配")
        self.logger.info("=" * 80)
        self.logger.info(f"Regions: {regions}")
        self.logger.info(f"Start Date: {start_date.date()}")
        self.logger.info(f"Min Alpha Count: {self.config['min_alpha_count']}")
        self.logger.info(f"分配方法: {self.config['allocation_method']}")
        self.logger.info(f"约束系统: {'启用' if self.config['apply_constraints'] else '禁用'}")
        mode = "正式执行（先 clear 再 update）" if update else "预览模式（不写入 API）"
        self.logger.info(f"运行模式: {mode}")
        self.logger.info("")

    def _print_region_report(self, region: str, df: pd.DataFrame):
        """打印单个 region 的详细分配结果"""
        cfg = self.config
        df = df.sort_values("assigned_score", ascending=False).reset_index(drop=True)

        self.logger.info(f"")
        self.logger.info(f"【{region}】分配结果: {len(df)} 个 Alpha, 总分={df['assigned_score'].sum()}")
        self.logger.info(f"  最高: {df['assigned_score'].max():,.0f}  |  "
                        f"最低: {df['assigned_score'].min():,.0f}  |  "
                        f"中位数: {df['assigned_score'].median():,.0f}")

        # SuperAlpha / REGULAR 分布
        if "type" in df.columns:
            super_count = (df["type"] == "SUPER").sum()
            regular_count = len(df) - super_count
            self.logger.info(f"  SuperAlpha: {super_count}  |  REGULAR: {regular_count}")

        # Top 15 详情
        display_cols = ["id", "type", "sharpe", "fitness", "turnover", "assigned_score"]
        available_cols = [c for c in display_cols if c in df.columns]
        self.logger.info(f"\n  Top 15:")
        for line in df[available_cols].head(15).to_string(index=False).split("\n"):
            self.logger.info(f"  {line}")

        # 分数分布（继承 V1 oss2.py）
        df["_bin"] = pd.cut(
            df["assigned_score"],
            bins=cfg["score_bins"],
            labels=cfg["score_bin_labels"],
        )
        bin_counts = df["_bin"].value_counts().sort_index()
        self.logger.info(f"\n  分数分布:")
        for bin_label, count in bin_counts.items():
            percentage = count / len(df) * 100
            bar_length = int(percentage / 2)
            bar = "█" * bar_length if bar_length > 0 else ""
            self.logger.info(f"    {bin_label:>8s}: {count:3d} 个 ({percentage:5.1f}%) {bar}")

    def _print_summary(self, results: List[Dict]):
        """打印总览表"""
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("总览")
        self.logger.info("=" * 80)
        df_summary = pd.DataFrame(results)
        for line in df_summary.to_string(index=False).split("\n"):
            self.logger.info(f"  {line}")

    def _print_failed_alphas(self, failed_alphas: List[str]):
        """打印更新失败的 Alpha"""
        unique_failed = list(dict.fromkeys(failed_alphas))  # 去重保序
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info(f"⚠️ 更新失败的 Alpha ({len(unique_failed)} 个)")
        self.logger.info("=" * 80)
        for aid in unique_failed:
            self.logger.info(f"  {aid}")

    # ==================================================================
    # 辅助
    # ==================================================================
    @staticmethod
    def _make_region_result(
        region: str,
        status: str,
        count: int,
        total: int,
        failed_alphas: List[str],
        **kwargs,
    ) -> Dict:
        """构造 region 结果字典"""
        result = {
            "region": region,
            "status": status,
            "count": count,
            "total": total,
            "failed_alphas": failed_alphas,
        }
        result.update(kwargs)
        return result


if __name__ == "__main__":
    """
    直接运行入口（无命令行参数）
    需要调整行为时，直接修改下方代码中的参数：
        update=False   # 设为 True 则先 clear 再 update
        dry_run=False  # 设为 True 则只预览不操作
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    runner = OsmosisRunnerV3()

    # 默认预览模式（不写入 API）
    # 需要正式执行时，将 update 改为 True
    runner.run(update=True)
