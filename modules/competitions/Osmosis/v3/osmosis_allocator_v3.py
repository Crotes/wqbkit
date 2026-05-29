import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import rankdata

_project_root = Path(__file__).resolve()
while "modules" in str(_project_root):
    _project_root = _project_root.parent
import sys
sys.path.insert(0, str(_project_root))

from wqbkit.app.core.alpha_base_core import AlphaBaseCore

logger = logging.getLogger(__name__)
API_BASE_URL = "https://api.worldquantbrain.com"
ALPHAS_URL = f"{API_BASE_URL}/alphas"


class OsmosisAllocatorV3(AlphaBaseCore):
    """
    Osmosis V3 约束化分配器

    在 V2 基础上新增：
    - 约束系统：单 Alpha / dataset_tags / neutralization 上限
    - Mixed 方法（默认）：quality + rank_decay + cluster_balance 组合
    - Config 驱动：所有参数可配置

    使用方式:
        allocator = OsmosisAllocatorV3()
        df = allocator.allocate(df, method="mixed", total_score=100000)
        allocator.update_osmosis_points(df)
    """

    DEFAULT_CONFIG = {
        # --- 约束参数 ---
        "min_score_per_alpha": 1,
        "max_score_per_alpha": 15000,
        "max_score_per_dataset_tags": 35000,
        "max_score_per_neutralization": 40000,
        # NOTE: cluster 约束已停用（primary_field 提取尚不成熟）
        # "max_score_per_cluster": 30000,
        "min_alpha_count": 10,
        "max_alpha_count": 35,
        "total_score": 100000,

        # --- Mixed 方法参数 ---
        "mixed_quality_weight": 0.50,
        "mixed_rank_weight": 0.25,
        "mixed_cluster_weight": 0.25,
        "mixed_temperature": 0.15,

        # --- Score Prop 方法参数 ---
        "score_prop_temperature": 0.15,

        # --- MDC 方法参数 ---
        "mdc_lambda_corr": 1.5,
        "mdc_temperature": 0.15,

        # --- 约束迭代 ---
        "constraint_max_iterations": 10,
        "constraint_convergence_tol": 1e-4,
    }

    def __init__(self, config: Optional[Dict] = None):
        super().__init__()
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self.logger.info("OsmosisAllocatorV3 initialized")

    # ==================================================================
    # 统一入口
    # ==================================================================
    def allocate(
        self,
        df: pd.DataFrame,
        method: str = "mixed",
        total_score: int = 100000,
        apply_constraints: bool = True,
        **kwargs,
    ) -> pd.DataFrame:
        """
        统一分配入口

        Args:
            df: 粗筛后的 DataFrame，必须包含 id + quality_score 列
            method: 分配方法（mixed / equal / score_prop / inverse_vol / mdc / greedy_sharpe / risk_parity）
            total_score: 总分数（默认 100000）
            apply_constraints: 是否应用约束后处理（默认 True）
            **kwargs: 各方法特有的额外参数

        Returns:
            带 assigned_score 列的 DataFrame
        """
        if df.empty:
            self.logger.error("输入 DataFrame 为空，无法分配")
            return df

        if "quality_score" not in df.columns:
            self.logger.warning("df 中无 quality_score 列，所有 Alpha 设为 0.5")
            df = df.copy()
            df["quality_score"] = 0.5

        df = df.copy()

        # 根据方法分配
        if method == "equal":
            df = self._allocate_equal(df, total_score)
        elif method == "score_prop":
            t = kwargs.get("temperature", self.config["score_prop_temperature"])
            df = self._allocate_score_proportional(df, total_score, temperature=t)
        elif method == "inverse_vol":
            df = self._allocate_inverse_volatility(df, total_score, **kwargs)
        elif method == "mdc":
            df = self._allocate_mdc(df, total_score, **kwargs)
        elif method == "mixed":
            df = self._allocate_mixed(df, total_score, **kwargs)
        elif method == "greedy_sharpe":
            returns = kwargs.get("returns_matrix")
            if returns is None or returns.empty:
                self.logger.error("greedy_sharpe 需要 returns_matrix")
                return df
            df = self._allocate_greedy_max_sharpe(df, returns, total_score)
        elif method == "risk_parity":
            returns = kwargs.get("returns_matrix")
            if returns is None or returns.empty:
                self.logger.error("risk_parity 需要 returns_matrix")
                return df
            df = self._allocate_risk_parity(df, returns, total_score)
        else:
            raise ValueError(f"未知分配方法: {method}")

        # 约束后处理
        if apply_constraints:
            df = self._apply_constraints(df, total_score)

        # 统一后处理：整数化、总分校准
        df = self._post_process(df, total_score)

        self.logger.info(
            f"[{method}] 分配完成: {len(df)} 个 Alpha, "
            f"总分={df['assigned_score'].sum()}, "
            f"最高={df['assigned_score'].max()}, 最低={df['assigned_score'].min()}"
        )
        return df

    # ==================================================================
    # 约束系统
    # ==================================================================
    def _apply_constraints(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """
        应用约束后处理

        流程：
        1. 单 Alpha 上限/下限裁剪
        2. 迭代应用 group 约束（dataset_tags / neutralization）
           - 超额 group 内按比例压缩
           - 压缩后重新校准总分（仅分配给未达上限的 Alpha）
        3. 最终单 Alpha 上限/下限裁剪
        """
        cfg = self.config
        df = df.copy()

        # 1. 单 Alpha 上限/下限
        df["assigned_score"] = df["assigned_score"].clip(
            lower=cfg["min_score_per_alpha"],
            upper=cfg["max_score_per_alpha"],
        )

        # 2. 迭代应用 group 约束
        for iteration in range(cfg["constraint_max_iterations"]):
            old_scores = df["assigned_score"].copy()

            # Dataset tags 约束
            df = self._apply_dataset_tags_constraint(df, cfg["max_score_per_dataset_tags"])

            # Neutralization 约束
            df = self._apply_neutralization_constraint(df, cfg["max_score_per_neutralization"])

            # NOTE: Cluster 约束已停用（primary_field 提取尚不成熟）
            # if "primary_field" in df.columns:
            #     df = self._apply_cluster_constraint(df, cfg.get("max_score_per_cluster", 30000))

            # 重新校准总分（仅分配给未达上限的 Alpha）
            df = self._redistribute_shortfall(df, total_score)

            # 检查收敛
            max_diff = (df["assigned_score"] - old_scores).abs().max()
            if max_diff < cfg["constraint_convergence_tol"]:
                break

        # 3. 最终单 Alpha 上限/下限
        df["assigned_score"] = df["assigned_score"].clip(
            lower=cfg["min_score_per_alpha"],
            upper=cfg["max_score_per_alpha"],
        )

        return df

    def _redistribute_shortfall(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """将 shortfall 按 quality_score 比例重新分配给未达上限的 Alpha"""
        cfg = self.config
        # 确保列是 float，避免 pandas dtype 警告
        df["assigned_score"] = df["assigned_score"].astype(float)
        current_total = df["assigned_score"].sum()
        shortfall = total_score - current_total

        if abs(shortfall) < 1:
            return df

        if shortfall > 0:
            # 需要增加总分
            for _ in range(100):
                eligible = df[df["assigned_score"] < cfg["max_score_per_alpha"]]
                if eligible.empty or shortfall < 1:
                    break
                q_scores = eligible["quality_score"].fillna(0.5)
                weights = q_scores / q_scores.sum()
                for idx in eligible.index:
                    max_add = cfg["max_score_per_alpha"] - df.at[idx, "assigned_score"]
                    add = min(weights.loc[idx] * shortfall, max_add)
                    df.at[idx, "assigned_score"] += add
                    shortfall -= add
                    if shortfall < 1:
                        break
        elif shortfall < 0:
            # 需要减少总分
            for _ in range(100):
                eligible = df[df["assigned_score"] > cfg["min_score_per_alpha"]]
                if eligible.empty or shortfall > -1:
                    break
                q_scores = eligible["quality_score"].fillna(0.5)
                weights = q_scores / q_scores.sum()
                for idx in eligible.index:
                    max_sub = df.at[idx, "assigned_score"] - cfg["min_score_per_alpha"]
                    sub = min(weights.loc[idx] * abs(shortfall), max_sub)
                    df.at[idx, "assigned_score"] -= sub
                    shortfall += sub
                    if shortfall > -1:
                        break

        return df

    def _apply_dataset_tags_constraint(
        self, df: pd.DataFrame, max_score: float
    ) -> pd.DataFrame:
        """对 dataset_tags 应用上限约束（多标签）"""
        if "dataset_tags" not in df.columns or df["dataset_tags"].isna().all():
            return df

        # Explode 多标签
        exploded = df.explode("dataset_tags")
        tag_sums = exploded.groupby("dataset_tags")["assigned_score"].sum()

        for tag, tag_total in tag_sums.items():
            if tag_total > max_score and tag != "unknown":
                scale = max_score / tag_total
                mask = df["dataset_tags"].apply(lambda tags: isinstance(tags, list) and tag in tags)
                df.loc[mask, "assigned_score"] *= scale

        return df

    def _apply_neutralization_constraint(
        self, df: pd.DataFrame, max_score: float
    ) -> pd.DataFrame:
        """对 neutralization 应用上限约束"""
        if "neutralization" not in df.columns or df["neutralization"].isna().all():
            return df

        group_sums = df.groupby("neutralization")["assigned_score"].sum()
        for group, group_total in group_sums.items():
            if group_total > max_score:
                scale = max_score / group_total
                mask = df["neutralization"] == group
                df.loc[mask, "assigned_score"] *= scale

        return df

    def _apply_cluster_constraint(
        self, df: pd.DataFrame, max_score: float
    ) -> pd.DataFrame:
        """对 primary_field + primary_op cluster 应用上限约束"""
        if "primary_field" not in df.columns or "primary_op" not in df.columns:
            return df

        df["_cluster"] = df["primary_field"].astype(str) + "::" + df["primary_op"].astype(str)
        group_sums = df.groupby("_cluster")["assigned_score"].sum()

        for cluster, cluster_total in group_sums.items():
            if cluster_total > max_score:
                scale = max_score / cluster_total
                mask = df["_cluster"] == cluster
                df.loc[mask, "assigned_score"] *= scale

        df = df.drop(columns=["_cluster"], errors="ignore")
        return df

    def _recalibrate_total(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """按比例重新校准总分到 total_score"""
        current_total = df["assigned_score"].sum()
        if current_total > 0 and not np.isclose(current_total, total_score):
            scale = total_score / current_total
            df["assigned_score"] *= scale
        return df

    # ==================================================================
    # 统一后处理：整数化 + 总分校准
    # ==================================================================
    def _post_process(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """
        统一后处理：
        1. 四舍五入到整数
        2. 确保总分 = total_score
        3. 确保每个 Alpha 在 [min_score_per_alpha, max_score_per_alpha] 范围内
        """
        df = df.copy()
        cfg = self.config
        df["assigned_score"] = df["assigned_score"].round().astype(int)
        df["assigned_score"] = df["assigned_score"].clip(
            lower=cfg["min_score_per_alpha"],
            upper=cfg["max_score_per_alpha"],
        )

        diff = total_score - df["assigned_score"].sum()

        if diff > 0:
            # 按比例分配余数（floor），剩余按 quality_score 排序逐点加
            q_scores = df["quality_score"].fillna(0.5)
            eligible_mask = df["assigned_score"] < cfg["max_score_per_alpha"]
            # 只在 eligible Alpha 中按比例分配
            weights = pd.Series(0.0, index=df.index)
            if eligible_mask.any():
                eligible_q = q_scores[eligible_mask]
                weights[eligible_mask] = eligible_q / eligible_q.sum()
            additions = (weights * diff).astype(int)
            remainder = diff - additions.sum()
            if remainder > 0 and eligible_mask.any():
                top_eligible = df[eligible_mask].nlargest(min(remainder, eligible_mask.sum()), "quality_score").index
                for idx in top_eligible:
                    additions.loc[idx] += 1
            # 不突破上限
            for idx in df.index:
                max_add = cfg["max_score_per_alpha"] - df.at[idx, "assigned_score"]
                additions.loc[idx] = min(additions.loc[idx], max(0, max_add))
            df["assigned_score"] += additions

        elif diff < 0:
            # 按比例扣减（floor），剩余按 quality_score 排序逐点扣
            q_scores = df["quality_score"].fillna(0.5)
            weights = q_scores / q_scores.sum()
            subtractions = (weights * abs(diff)).astype(int)
            remainder = abs(diff) - subtractions.sum()
            if remainder > 0:
                bottom_idx = df.nsmallest(remainder, "quality_score").index
                for idx in bottom_idx:
                    subtractions.loc[idx] += 1
            # 实际扣减时检查下限
            for idx in df.index:
                actual_sub = min(
                    subtractions.loc[idx],
                    df.at[idx, "assigned_score"] - cfg["min_score_per_alpha"],
                )
                df.at[idx, "assigned_score"] -= actual_sub

        return df

    # ==================================================================
    # 分配方法实现
    # ==================================================================
    def _allocate_mixed(
        self,
        df: pd.DataFrame,
        total_score: int,
        **kwargs,
    ) -> pd.DataFrame:
        """
        Mixed 方法（V3 默认）：
        final_weight = quality_weight * softmax(quality_score)
                     + rank_weight * rank_decay
                     + cluster_weight * cluster_balance
        """
        cfg = self.config
        quality_weight = kwargs.get("quality_weight", cfg["mixed_quality_weight"])
        rank_weight = kwargs.get("rank_weight", cfg["mixed_rank_weight"])
        cluster_weight = kwargs.get("cluster_weight", cfg["mixed_cluster_weight"])
        temperature = kwargs.get("temperature", cfg["mixed_temperature"])

        # 1. Quality weights (softmax)
        q_scores = df["quality_score"].values
        exp_q = np.exp((q_scores - q_scores.max()) / max(temperature, 1e-10))
        q_weights = exp_q / exp_q.sum()

        # 2. Rank decay weights
        df_sorted = df.sort_values("quality_score", ascending=False).reset_index(drop=True)
        ranks = np.arange(1, len(df_sorted) + 1)
        r_weights = 1.0 / np.sqrt(ranks)
        r_weights = r_weights / r_weights.sum()
        df_sorted["rank_weight"] = r_weights
        rank_map = dict(zip(df_sorted["id"], df_sorted["rank_weight"]))
        df["rank_weight"] = df["id"].map(rank_map).fillna(1.0 / len(df))

        # 3. Cluster balancing weights
        # fallback: primary_field > neutralization
        cluster_col = "primary_field" if "primary_field" in df.columns else "neutralization"
        if cluster_col in df.columns:
            cluster_scores = df.groupby(cluster_col)["quality_score"].transform("sum")
            cluster_balance = 1.0 / (1.0 + cluster_scores / cluster_scores.mean())
            cluster_balance = cluster_balance / cluster_balance.sum()
            cluster_balance_vals = cluster_balance.values
        else:
            cluster_balance_vals = np.ones(len(df)) / len(df)

        # 组合
        final_weights = (
            quality_weight * q_weights
            + rank_weight * df["rank_weight"].values
            + cluster_weight * cluster_balance_vals
        )
        final_weights = final_weights / final_weights.sum()
        df["assigned_score"] = final_weights * total_score
        return df

    def _allocate_equal(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """等权分配 — 基准对照"""
        n = len(df)
        base = total_score / n
        df["assigned_score"] = base
        return df

    def _allocate_score_proportional(
        self,
        df: pd.DataFrame,
        total_score: int,
        temperature: float = 0.15,
    ) -> pd.DataFrame:
        """
        按 quality_score 比例分配（改进版 softmax）
        temperature 控制集中度:
        - 0.05: 非常集中
        - 0.15: 中等集中（推荐）
        - 0.30: 比较分散
        """
        scores = df["quality_score"].values
        exp_scores = np.exp((scores - scores.max()) / max(temperature, 1e-10))
        probs = exp_scores / exp_scores.sum()
        df["assigned_score"] = probs * total_score
        return df

    def _allocate_inverse_volatility(
        self,
        df: pd.DataFrame,
        total_score: int,
        vol_proxy: Optional[str] = None,
    ) -> pd.DataFrame:
        """逆波动率权重"""
        if vol_proxy and vol_proxy in df.columns:
            vol = df[vol_proxy].abs()
        else:
            vol = df["drawdown"].abs().fillna(0) + df["turnover"].fillna(0) * 0.3

        vol = vol.replace(0, vol[vol > 0].min() * 0.1)
        inv_vol = 1.0 / vol
        weights = inv_vol / inv_vol.sum()
        df["assigned_score"] = weights * total_score
        return df

    def _allocate_mdc(
        self,
        df: pd.DataFrame,
        total_score: int,
        lambda_corr: float = 1.5,
        temperature: float = 0.15,
    ) -> pd.DataFrame:
        """
        Marginal Diversification Contribution (边际分散化贡献)
        effective_score = composite_score / (1 + λ × avg_corr_to_better)
        """
        df = df.sort_values("quality_score", ascending=False).reset_index(drop=True)
        effective_scores = []

        for i, row in df.iterrows():
            if i == 0:
                effective_scores.append(row["quality_score"])
            else:
                corr = row.get("prodCorrelation", 0.5)
                if pd.isna(corr):
                    corr = 0.5
                discount = 1.0 / (1.0 + lambda_corr * corr)
                effective_scores.append(row["quality_score"] * discount)

        df["effective_score"] = effective_scores
        exp_scores = np.exp(
            (df["effective_score"] - df["effective_score"].max()) / max(temperature, 1e-10)
        )
        probs = exp_scores / exp_scores.sum()
        df["assigned_score"] = probs * total_score
        return df

    def _allocate_greedy_max_sharpe(
        self,
        df: pd.DataFrame,
        returns: pd.DataFrame,
        total_score: int,
        min_alpha: int = 10,
        max_alpha: int = 35,
    ) -> pd.DataFrame:
        """基于 PnL 的贪心最大 Sharpe"""
        alpha_ids = [aid for aid in df["id"] if aid in returns.columns]
        if not alpha_ids:
            self.logger.error("df 中的 Alpha ID 与 returns 矩阵无交集")
            return df

        selected = []
        remaining = alpha_ids.copy()
        best_sharpe = -np.inf

        while remaining and len(selected) < max_alpha:
            best_candidate = None
            best_candidate_sharpe = -np.inf

            for aid in remaining:
                trial = selected + [aid]
                trial_returns = returns[trial].mean(axis=1)
                if trial_returns.std() == 0:
                    continue
                sharpe = trial_returns.mean() / trial_returns.std()
                if sharpe > best_candidate_sharpe:
                    best_candidate_sharpe = sharpe
                    best_candidate = aid

            if best_candidate is None:
                break

            if len(selected) >= min_alpha and best_candidate_sharpe <= best_sharpe:
                break

            selected.append(best_candidate)
            remaining.remove(best_candidate)
            best_sharpe = best_candidate_sharpe

        self.logger.info(f"greedy_sharpe 选中 {len(selected)} 个 Alpha")

        selected_returns = returns[selected]
        vols = selected_returns.std()
        vols = vols.replace(0, vols[vols > 0].min() * 0.1)
        inv_vols = 1.0 / vols
        weights = inv_vols / inv_vols.sum()

        weight_map = dict(zip(selected, weights))
        df["weight"] = df["id"].map(weight_map).fillna(0)
        df["assigned_score"] = df["weight"] * total_score
        return df

    def _allocate_risk_parity(
        self,
        df: pd.DataFrame,
        returns: pd.DataFrame,
        total_score: int,
    ) -> pd.DataFrame:
        """风险平价: 每个 Alpha 对组合风险的边际贡献相等（简化版）"""
        alpha_ids = [aid for aid in df["id"] if aid in returns.columns]
        if not alpha_ids:
            self.logger.error("df 中的 Alpha ID 与 returns 矩阵无交集")
            return df

        sub_returns = returns[alpha_ids]
        vols = sub_returns.std()
        vols = vols.replace(0, vols[vols > 0].min() * 0.1)
        inv_vols = 1.0 / vols
        weights = inv_vols / inv_vols.sum()

        weight_map = dict(zip(alpha_ids, weights))
        df["weight"] = df["id"].map(weight_map).fillna(0)
        df["assigned_score"] = df["weight"] * total_score
        return df

    # ==================================================================
    # API 写入
    # ==================================================================
    def update_osmosis_points(self, df: pd.DataFrame, dry_run: bool = False) -> Dict[str, int]:
        """
        将 assigned_score 写入 WQB API

        Args:
            df: 带 assigned_score 列的 DataFrame
            dry_run: 若为 True，只打印不实际调用 API

        Returns:
            {alpha_id: status_code} 映射
        """
        results = {}
        for _, row in df.iterrows():
            alpha_id = row["id"]
            score = int(row["assigned_score"])

            if dry_run:
                self.logger.info(f"[DRY RUN] {alpha_id} -> {score}")
                results[alpha_id] = 200
                continue

            try:
                url = f"{ALPHAS_URL}/{alpha_id}"
                resp = self.patch(url, json={"osmosisPoints": score})
                results[alpha_id] = resp.status_code
                if resp.status_code == 200:
                    self.logger.info(f"✓ {alpha_id}: {score}")
                else:
                    self.logger.error(f"✗ {alpha_id}: HTTP {resp.status_code}")
            except Exception as e:
                self.logger.error(f"✗ {alpha_id}: {e}")
                results[alpha_id] = -1

        success = sum(1 for s in results.values() if s == 200)
        self.logger.info(f"API 更新完成: {success}/{len(results)} 成功")
        return results
