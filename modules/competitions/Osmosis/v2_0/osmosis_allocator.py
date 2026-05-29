import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

"""
Osmosis 分数分配器

提供多种从组合理论出发的分配策略，核心目标：
把 100,000 points 分配到 N 个 Alpha 上，使组合层面的 Sharpe / 稳定性最优。

策略谱系（从简单到复杂）：
1. equal              — 等权，基准对照
2. score_prop         — 按质量评分比例分配（改进版 softmax）
3. inverse_vol        — 逆波动率权重，低波动 Alpha 多拿
4. mdc                — 边际分散化贡献，惩罚高相关冗余
5. greedy_sharpe      — 基于 PnL 的贪心最大 Sharpe（需 returns）
6. risk_parity        — 风险平价，每个 Alpha 风险贡献相等（需 returns）
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from wqbkit.app.core.alpha_base_core import AlphaBaseCore

logger = logging.getLogger(__name__)
API_BASE_URL = "https://api.worldquantbrain.com"
ALPHAS_URL = f"{API_BASE_URL}/alphas"


class OsmosisAllocator(AlphaBaseCore):
    """
    Osmosis 分数分配器

    使用方式:
        allocator = OsmosisAllocator()

        # 方法 1: 基于质量评分分配
        df = allocator.allocate(df, method="score_prop", total_score=100000)

        # 方法 2: 基于 PnL 的贪心最大 Sharpe
        df = allocator.allocate(df, method="greedy_sharpe", total_score=100000,
                                returns_matrix=returns_df)

        # 写入 API
        allocator.update_osmosis_points(df)
    """

    def __init__(self):
        super().__init__()
        self.logger.info("OsmosisAllocator initialized")

    # ==================================================================
    # 统一入口
    # ==================================================================
    def allocate(
        self,
        df: pd.DataFrame,
        method: str = "score_prop",
        total_score: int = 100000,
        **kwargs,
    ) -> pd.DataFrame:
        """
        统一分配入口

        Args:
            df: 粗筛后的 DataFrame，必须包含 id + IS 指标列
            method: 分配方法
            total_score: 总分数（默认 100000）
            **kwargs: 各方法特有的额外参数

        Returns:
            带 assigned_score 列的 DataFrame
        """
        if df.empty:
            logger.error("输入 DataFrame 为空，无法分配")
            return df

        # 先计算 composite_score（所有方法共享）
        df = self._compute_composite_score(df)

        if method == "equal":
            df = self._allocate_equal(df, total_score)
        elif method == "score_prop":
            df = self._allocate_score_proportional(df, total_score, **kwargs)
        elif method == "inverse_vol":
            df = self._allocate_inverse_volatility(df, total_score, **kwargs)
        elif method == "mdc":
            df = self._allocate_mdc(df, total_score, **kwargs)
        elif method == "greedy_sharpe":
            returns = kwargs.get("returns_matrix")
            if returns is None or returns.empty:
                logger.error("greedy_sharpe 需要 returns_matrix")
                return df
            df = self._allocate_greedy_max_sharpe(df, returns, total_score)
        elif method == "risk_parity":
            returns = kwargs.get("returns_matrix")
            if returns is None or returns.empty:
                logger.error("risk_parity 需要 returns_matrix")
                return df
            df = self._allocate_risk_parity(df, returns, total_score)
        else:
            raise ValueError(f"未知分配方法: {method}")

        # 统一后处理：整数化、总分校准
        df = self._post_process(df, total_score)

        self.logger.info(
            f"[{method}] 分配完成: {len(df)} 个 Alpha, "
            f"总分={df['assigned_score'].sum()}, "
            f"最高={df['assigned_score'].max()}, 最低={df['assigned_score'].min()}"
        )
        return df

    # ==================================================================
    # 1. 基础工具：计算 composite_score
    # ==================================================================
    def _compute_composite_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算每个 Alpha 的综合质量评分

        指标：fitness / sharpe / returns / margin / drawdown / turnover / balance
        所有指标先做 rankdata 标准化（0-1），再线性加权
        """
        from scipy.stats import rankdata

        weights = {
            "fitness": 0.25,
            "sharpe": 0.25,
            "returns": 0.15,
            "margin": 0.15,
            "drawdown": 0.10,
            "turnover": 0.05,
            "balance": 0.05,
        }

        # 确保列存在
        for col in weights.keys():
            if col not in df.columns:
                if col == "balance":
                    df[col] = 0.5  # 默认值
                else:
                    df[col] = 0.0

        # 计算 balance（如果还没有）
        if "balance" not in df.columns or df["balance"].isna().all():
            if "longCount" in df.columns and "shortCount" in df.columns:
                df["balance"] = df.apply(
                    lambda r: min(r["longCount"], r["shortCount"]) / max(r["longCount"], r["shortCount"])
                    if max(r["longCount"], r["shortCount"]) > 0 else 0,
                    axis=1,
                )
            else:
                df["balance"] = 0.5

        # Rankdata 标准化（越大越好）
        for col in ["fitness", "sharpe", "returns", "margin"]:
            if len(df) > 1 and df[col].nunique() > 1:
                df[f"{col}_score"] = rankdata(df[col].fillna(0)) / len(df)
            else:
                df[f"{col}_score"] = 0.5

        # drawdown 越小越好
        if len(df) > 1 and df["drawdown"].nunique() > 1:
            neg_dd = -df["drawdown"].fillna(df["drawdown"].max() if df["drawdown"].max() > 0 else 1)
            df["drawdown_score"] = rankdata(neg_dd) / len(df)
        else:
            df["drawdown_score"] = 0.5

        # turnover：理想 < 20%，但粗筛已经保证
        df["turnover_score"] = 1.0 - (df["turnover"] / 25.0).clip(0, 1)

        # 加权
        df["composite_score"] = (
            weights["fitness"] * df["fitness_score"] +
            weights["sharpe"] * df["sharpe_score"] +
            weights["returns"] * df["returns_score"] +
            weights["margin"] * df["margin_score"] +
            weights["drawdown"] * df["drawdown_score"] +
            weights["turnover"] * df["turnover_score"] +
            weights["balance"] * df["balance"]
        )

        # 归一化到 [0, 1]
        if df["composite_score"].nunique() > 1:
            score_min = df["composite_score"].min()
            score_max = df["composite_score"].max()
            if score_max > score_min:
                df["composite_score"] = (df["composite_score"] - score_min) / (score_max - score_min)
        else:
            df["composite_score"] = 0.5

        return df

    # ==================================================================
    # 2. 统一后处理：整数化 + 总分校准
    # ==================================================================
    def _post_process(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """
        统一后处理：
        1. 四舍五入到整数
        2. 确保总分 = total_score
        3. 确保每个 Alpha >= 1（如果池子过大，可能有些拿不到分，但至少 1）
        """
        df = df.copy()
        df["assigned_score"] = df["assigned_score"].round().astype(int)
        df["assigned_score"] = df["assigned_score"].clip(lower=1)

        diff = total_score - df["assigned_score"].sum()

        if diff > 0:
            # 把余数加到 composite_score 最高的 Alpha 上
            top_idx = df.nlargest(diff, "composite_score").index
            df.loc[top_idx, "assigned_score"] += 1
        elif diff < 0:
            # 从 composite_score 最低的 Alpha 扣减（保底 1）
            bottom_idx = df.nsmallest(abs(diff), "composite_score").index
            for idx in bottom_idx:
                if df.at[idx, "assigned_score"] > 1:
                    df.at[idx, "assigned_score"] -= 1
                    diff += 1
                    if diff == 0:
                        break

        return df

    # ==================================================================
    # 3. 分配方法实现
    # ==================================================================
    def _allocate_equal(self, df: pd.DataFrame, total_score: int) -> pd.DataFrame:
        """等权分配 — 基准对照"""
        n = len(df)
        base = total_score // n
        df["assigned_score"] = base
        return df

    def _allocate_score_proportional(
        self,
        df: pd.DataFrame,
        total_score: int,
        temperature: float = 0.15,
    ) -> pd.DataFrame:
        """
        按 composite_score 比例分配（改进版 softmax）

        temperature 控制集中度:
        - 0.05: 非常集中，头部 3-5 个拿大部分
        - 0.15: 中等集中（推荐）
        - 0.30: 比较分散
        """
        scores = df["composite_score"].values
        # numerical stability
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
        """
        逆波动率权重

        vol_proxy: 波动率代理列名，默认用 drawdown 绝对值
        """
        if vol_proxy and vol_proxy in df.columns:
            vol = df[vol_proxy].abs()
        else:
            # 综合代理：drawdown + turnover 贡献
            vol = df["drawdown"].abs().fillna(0) + df["turnover"].fillna(0) * 0.3

        vol = vol.replace(0, vol[vol > 0].min() * 0.1)  # 避免除以 0
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

        核心思想：与高分 Alpha 高度相关的，effective_score 打折
        effective_score = composite_score / (1 + λ × avg_corr_to_better)
        """
        df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
        effective_scores = []

        for i, row in df.iterrows():
            if i == 0:
                effective_scores.append(row["composite_score"])
            else:
                # 用 prodCorrelation 代理与前序 Alpha 的相关性
                # 如果 prodCorrelation 缺失，默认 0.5（中等相关）
                corr = row.get("prodCorrelation", 0.5)
                if pd.isna(corr):
                    corr = 0.5
                discount = 1.0 / (1.0 + lambda_corr * corr)
                effective_scores.append(row["composite_score"] * discount)

        df["effective_score"] = effective_scores
        exp_scores = np.exp((df["effective_score"] - df["effective_score"].max()) / max(temperature, 1e-10))
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
        """
        基于 PnL 的贪心最大 Sharpe

        步骤：
        1. 从空集开始，每次选择加入后组合 Sharpe 提升最大的 Alpha
        2. 直到边际贡献为负或达到 max_alpha
        3. 对选中的 Alpha 按 inverse volatility 分配权重
        """
        alpha_ids = [aid for aid in df["id"] if aid in returns.columns]
        if not alpha_ids:
            logger.error("df 中的 Alpha ID 与 returns 矩阵无交集")
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

        logger.info(f"greedy_sharpe 选中 {len(selected)} 个 Alpha")

        # 对选中的按 inverse vol 分配
        selected_returns = returns[selected]
        vols = selected_returns.std()
        vols = vols.replace(0, vols[vols > 0].min() * 0.1)
        inv_vols = 1.0 / vols
        weights = inv_vols / inv_vols.sum()

        # 映射回完整 df
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
        """
        风险平价: 每个 Alpha 对组合风险的边际贡献相等

        简化实现：权重 ∝ 1/σ_i（如果 Alpha 间相关性不高，近似成立）
        严格实现需要迭代求解（此处用简化版）
        """
        alpha_ids = [aid for aid in df["id"] if aid in returns.columns]
        if not alpha_ids:
            logger.error("df 中的 Alpha ID 与 returns 矩阵无交集")
            return df

        sub_returns = returns[alpha_ids]
        cov = sub_returns.cov()
        vols = sub_returns.std()

        # 简化风险平价：权重 ∝ 1/σ_i
        # 严格版：权重 w 满足 w_i × (Σw)_i / (w'Σw) = 1/n
        vols = vols.replace(0, vols[vols > 0].min() * 0.1)
        inv_vols = 1.0 / vols
        weights = inv_vols / inv_vols.sum()

        weight_map = dict(zip(alpha_ids, weights))
        df["weight"] = df["id"].map(weight_map).fillna(0)
        df["assigned_score"] = df["weight"] * total_score
        return df

    # ==================================================================
    # 4. API 写入
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
