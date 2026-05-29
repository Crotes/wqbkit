import json
import logging
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from tqdm import tqdm
from wqb import FilterRange

from wqbkit.modules.correlation.alpha_calc_corr import AlphaCalcCorr

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))


class OsmosisAlphaSelector(AlphaCalcCorr):
    """
    Osmosis 粗筛器 — 基于 app 框架能力构建

    继承链: OsmosisAlphaSelector -> AlphaCalcCorr -> AlphaDbCore -> AlphaBaseCore

    功能:
    - 三层粗筛: 硬性门槛 → 相关性过滤 → 策略分散
    - 黑名单: 持久化排除指定 Alpha
    - 缓存: 候选列表本地缓存(默认60分钟)
    - 动态限额: 策略分散的 top_k 随池子大小自适应

    使用方式:
        selector = OsmosisAlphaSelector()
        df = selector.select(region="USA", start_date=datetime(2025, 4, 19))

        # 拉黑表现差的 Alpha
        selector.add_to_blacklist(["alpha_id_1", "alpha_id_2"])

        # 强制刷新缓存重跑
        selector.clear_cache("candidates")
        df = selector.select(region="USA", start_date=datetime(2025, 4, 19))
    """

    # ------------------------------------------------------------------
    # 默认配置
    # ------------------------------------------------------------------
    DEFAULT_CONFIG = {
        "max_turnover": 20.0,      # MD: avoid turnover > 20%
        "min_sharpe": 1.0,         # IS Sharpe 基础门槛
        "min_fitness": 0.3,        # Fitness 门槛（设低避免过度杀）
        "max_drawdown": 25.0,      # 最大回撤 %
        "min_returns": 0.0,        # 必须正收益
        "max_prod_corr": 0.7,      # prod correlation 上限
        "min_alpha_count": 10,     # 单 scope 最少保留数量
    }

    # 缓存有效期(分钟)
    CACHE_TTL_MINUTES = 60

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict] = None):
        super().__init__()
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        # 缓存与黑名单目录
        self.cache_dir = Path(__file__).parent / "data" / "selector_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 黑名单
        self.blacklist_path = self.cache_dir / "blacklist.json"
        self.blacklist: set = self._load_blacklist()

        self.logger.info(
            f"OsmosisAlphaSelector init: blacklist={len(self.blacklist)} items, "
            f"cache_dir={self.cache_dir}"
        )

    # ==================================================================
    # 黑名单管理
    # ==================================================================
    def _load_blacklist(self) -> set:
        """从 JSON 加载黑名单"""
        if not self.blacklist_path.exists():
            return set()
        try:
            with open(self.blacklist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("alpha_ids", []))
        except Exception as e:
            self.logger.error(f"加载黑名单失败: {e}")
            return set()

    def _save_blacklist(self) -> None:
        """保存黑名单到 JSON"""
        try:
            with open(self.blacklist_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "alpha_ids": sorted(list(self.blacklist)),
                        "updated_at": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            self.logger.error(f"保存黑名单失败: {e}")

    def add_to_blacklist(self, alpha_ids: Union[str, List[str]], reason: str = "") -> None:
        """添加 Alpha 到黑名单"""
        if isinstance(alpha_ids, str):
            alpha_ids = [alpha_ids]
        alpha_ids = [aid for aid in alpha_ids if aid]
        if not alpha_ids:
            return
        self.blacklist.update(alpha_ids)
        self._save_blacklist()
        self.logger.info(f"Blacklist +{len(alpha_ids)} (reason={reason})")

    def remove_from_blacklist(self, alpha_ids: Union[str, List[str]]) -> None:
        """从黑名单移除"""
        if isinstance(alpha_ids, str):
            alpha_ids = [alpha_ids]
        alpha_ids = [aid for aid in alpha_ids if aid in self.blacklist]
        if not alpha_ids:
            return
        self.blacklist.difference_update(alpha_ids)
        self._save_blacklist()
        self.logger.info(f"Blacklist -{len(alpha_ids)}: {alpha_ids}")

    def clear_blacklist(self) -> None:
        """清空黑名单"""
        count = len(self.blacklist)
        self.blacklist.clear()
        self._save_blacklist()
        self.logger.info(f"Blacklist cleared ({count} items)")

    def is_blacklisted(self, alpha_id: str) -> bool:
        return alpha_id in self.blacklist

    def list_blacklist(self) -> List[str]:
        return sorted(list(self.blacklist))

    # ==================================================================
    # 缓存管理
    # ==================================================================
    def _cache_path(self, cache_type: str, key: str) -> Path:
        return self.cache_dir / f"{cache_type}_{key}.pkl"

    def _load_cache(self, cache_type: str, key: str, max_age_minutes: int = 60) -> Optional[pd.DataFrame]:
        path = self._cache_path(cache_type, key)
        if not path.exists():
            return None
        try:
            if time.time() - path.stat().st_mtime > max_age_minutes * 60:
                self.logger.info(f"Cache expired: {cache_type}/{key}")
                return None
            with open(path, "rb") as f:
                obj = pickle.load(f)
            self.logger.info(f"Cache hit: {cache_type}/{key}")
            return obj
        except Exception as e:
            self.logger.warning(f"Cache load failed: {e}")
            return None

    def _save_cache(self, cache_type: str, key: str, obj: pd.DataFrame) -> None:
        path = self._cache_path(cache_type, key)
        try:
            with open(path, "wb") as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            self.logger.error(f"Cache save failed: {e}")

    def clear_cache(self, cache_type: Optional[str] = None) -> None:
        removed = 0
        for path in self.cache_dir.glob("*.pkl"):
            if cache_type is None or path.name.startswith(f"{cache_type}_"):
                path.unlink(missing_ok=True)
                removed += 1
        self.logger.info(f"Cache cleared: {removed} files" + (f" (type={cache_type})" if cache_type else ""))

    # ==================================================================
    # 数据获取
    # ==================================================================
    def _fetch_candidates_from_api(
        self,
        region: str,
        delay: Optional[int] = None,
        type_filter: Optional[str] = None,
    ) -> pd.DataFrame:
        """从 WQB API 分页获取原始候选 Alpha"""
        filters = {
            "status": "ACTIVE",
            "region": region,
            "order": "dateSubmitted",
            "log": None,
        }

        if type_filter is not None:
            filters["type"] = type_filter

            if type_filter == 'REGULAR':
                # 不同 region 的 margin 门槛
                margin_threshold = 0.001 if region in ("USA", "EUR") else 0.0015
                filters["margin"] = FilterRange.from_str(f"[{margin_threshold}, inf)")
            elif type_filter == 'SUPER':
                filters["sharpe"] = FilterRange.from_str("[4, inf)")
                filters["fitness"] = FilterRange.from_str("[4, inf)")

        if delay is not None:
            filters["delay"] = delay

        alphas = []
        for resp in self.wqbs.filter_alphas(**filters):
            if resp is None:
                continue
            try:
                data = resp.json()
                if data is None:
                    continue
                for item in tqdm(data["results"]):
                    if item is None:
                        continue
                    parsed = self._parse_alpha_item(item)
                    if parsed:
                        alphas.append(parsed)
            except Exception as e:
                self.logger.error(f"解析 alpha 数据失败: {e}")

        if not alphas:
            self.logger.warning("未获取到任何候选 Alpha")
            return pd.DataFrame()

        return pd.DataFrame(alphas)

    def fetch_candidates(
        self,
        region: str,
        start_date: Optional[datetime] = None,
        delay: Optional[int] = None,
        type_filter: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        获取候选 Alpha，支持缓存与黑名单过滤

        Args:
            region: 目标 region
            start_date: 创建日期下限
            delay: 可选 delay
            type_filter: Alpha 类型
            use_cache: 是否使用本地缓存(默认60分钟)

        Returns:
            经过黑名单过滤后的候选 DataFrame
        """
        cache_key = f"{region}_{delay or 'any'}_{type_filter}"

        # 1. 尝试缓存
        if use_cache:
            df = self._load_cache("candidates", cache_key, self.CACHE_TTL_MINUTES)
            if df is not None:
                self.logger.info(f"fetch_candidates: 从缓存加载 {len(df)} 个")
            else:
                df = self._fetch_candidates_from_api(region, delay, type_filter)
                if not df.empty:
                    self._save_cache("candidates", cache_key, df)
        else:
            df = self._fetch_candidates_from_api(region, delay, type_filter)

        if df.empty:
            return df

        # 2. 黑名单过滤(每次必做，黑名单可能已更新)
        before = len(df)
        df = df[~df["id"].isin(self.blacklist)].copy()
        removed = before - len(df)
        if removed:
            self.logger.info(f"Blacklist filtered: -{removed}")

        # 3. 本地过滤 start_date
        if start_date:
            df["dateCreated"] = pd.to_datetime(df["dateCreated"], errors="coerce", utc=True).dt.tz_localize(None)
            start_date_naive = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
            df = df[df["dateCreated"] >= start_date_naive].copy()

        self.logger.info(f"fetch_candidates: 最终返回 {len(df)} 个 Alpha")
        return df

    @staticmethod
    def _parse_alpha_item(item: Dict) -> Optional[Dict]:
        """解析 WQB alpha item，排除 FastD1 / COMPENSATED / DECOMMISSIONED"""
        classifications = item.get("classifications", [])
        checks = item.get("is", {}).get("checks", [])

        is_fastd1 = any(c.get("name") == "FastD1 Alpha" for c in classifications)
        is_compensated = any(
            c.get("name") == "COMPENSATED_ALPHA" and c.get("result") == "WARNING"
            for c in checks
        )

        if is_fastd1 or is_compensated or item.get("status") == "DECOMMISSIONED":
            return None

        is_data = item.get("is", {})
        settings = item.get("settings", {})

        return {
            "id": item["id"],
            "fitness": is_data.get("fitness", 0.0),
            "sharpe": is_data.get("sharpe", 0.0),
            "returns": is_data.get("returns", 0.0),
            "drawdown": is_data.get("drawdown", 0.0),
            "margin": is_data.get("margin", 0.0),
            "turnover": is_data.get("turnover", 0.0),
            "longCount": is_data.get("longCount", 0.0),
            "shortCount": is_data.get("shortCount", 0.0),
            "expression": item.get("regular", {}).get("code", ""),
            "neutralization": settings.get("neutralization", "unknown"),
            "decay": settings.get("decay", -1),
            "dateCreated": item.get("dateCreated"),
            "dateSubmitted": item.get("dateSubmitted"),
            "status": item.get("status"),
            "type": item.get("type", "REGULAR"),
            "prodCorrelation": is_data.get("prodCorrelation", None),
        }

    # ==================================================================
    # 三层筛选
    # ==================================================================
    def apply_hard_filters(self, df: pd.DataFrame, relaxed: bool = False) -> pd.DataFrame:
        """Layer 1: 硬性质量门槛"""
        if df.empty:
            return df

        cfg = self.config

        if not relaxed:
            mask = (
                (df["turnover"] < cfg["max_turnover"]) &
                (df["sharpe"] > cfg["min_sharpe"]) &
                (df["fitness"] > cfg["min_fitness"]) &
                (df["drawdown"].abs() < cfg["max_drawdown"]) &
                (df["returns"] > cfg["min_returns"]) &
                (df["returns"] > df["drawdown"].abs())
            )
            label = "标准"
        else:
            mask = (
                (df["turnover"] < 25.0) &
                (df["sharpe"] > 0.8) &
                (df["fitness"] > 0.2) &
                (df["drawdown"].abs() < 30.0) &
                (df["returns"] > 0) &
                (df["returns"] > df["drawdown"].abs())
            )
            label = "放宽"

        filtered = df[mask].copy()
        self.logger.info(f"Layer 1 ({label}): {len(df)} -> {len(filtered)}")
        return filtered

    def apply_correlation_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 2: 相关性过滤

        优先使用 is['prodCorrelation'](零额外 API)，缺失则 fallback 到 calculate('prod')
        """
        if df.empty or len(df) <= self.config["min_alpha_count"]:
            return df

        threshold = self.config["max_prod_corr"]
        has_prod_corr = df["prodCorrelation"].notna().sum()

        if has_prod_corr == len(df):
            df["prod_corr"] = df["prodCorrelation"]
            self.logger.info(f"Layer 2: 内置 prodCorrelation ({len(df)} 个)")
        elif has_prod_corr > 0:
            missing_ids = df[df["prodCorrelation"].isna()]["id"].tolist()
            self.logger.info(f"Layer 2: {has_prod_corr} 内置, {len(missing_ids)} 调 API")
            try:
                corr_results = self.calculate(missing_ids, calc_type="prod")
                df["prod_corr"] = df.apply(
                    lambda row: row["prodCorrelation"]
                    if pd.notna(row["prodCorrelation"])
                    else corr_results.get(row["id"], 1.0),
                    axis=1,
                )
            except Exception as e:
                self.logger.error(f"补充 prodCorrelation 失败: {e}，跳过")
                return df
        else:
            self.logger.info(f"Layer 2: 调 API 计算 {len(df)} 个")
            try:
                corr_results = self.calculate(df["id"].tolist(), calc_type="prod")
                df["prod_corr"] = df["id"].map(lambda aid: corr_results.get(aid, 1.0))
            except Exception as e:
                self.logger.error(f"相关性过滤失败: {e}，跳过")
                return df

        df_pass = df[df["prod_corr"] < threshold].copy()
        self.logger.info(f"Layer 2: {len(df)} -> {len(df_pass)}")

        if len(df_pass) >= self.config["min_alpha_count"]:
            return df_pass.drop(columns=["prod_corr", "prodCorrelation"], errors="ignore")
        else:
            self.logger.warning(f"Layer 2 后仅 {len(df_pass)} 个，不足门槛，跳过此层")
            return df.drop(columns=["prod_corr", "prodCorrelation"], errors="ignore")

    def apply_diversification_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 3: 策略分散(动态限额)

        SuperAlpha(expression为空)本身是系统组合，已内置分散逻辑，
        直接保留不参与限额。仅对 REGULAR Alpha 按 operator/datafield 限额。
        """
        if df.empty:
            return df

        # 分离 SuperAlpha 和 REGULAR Alpha
        mask_super = df["type"] == "SUPER"
        df_super = df[mask_super].copy() if mask_super.any() else pd.DataFrame()
        df_regular = df[~mask_super].copy() if (~mask_super).any() else pd.DataFrame()

        if df_regular.empty:
            self.logger.info(f"Layer 3: 无 REGULAR Alpha，保留 {len(df_super)} 个 SuperAlpha")
            return df_super

        # 仅对 REGULAR Alpha 做策略分散
        def get_sig(expr: str) -> Tuple[str, str]:
            if not expr:
                return "unknown", "unknown"
            try:
                ops, fields = self.extract_tokens(expr)
                return (ops[0] if ops else "none", fields[0] if fields else "none")
            except Exception:
                return "unknown", "unknown"

        sigs = df_regular["expression"].apply(get_sig)
        df_regular["primary_op"] = sigs.apply(lambda x: x[0])
        df_regular["primary_field"] = sigs.apply(lambda x: x[1])

        n = len(df_regular)
        top_k_field = max(3, min(12, n // 12))
        top_k_op = max(2, min(8, n // 20))

        self.logger.info(f"Layer 3: REGULAR={n}个, field限额={top_k_field}, op限额={top_k_op}, SuperAlpha={len(df_super)}个直接保留")

        df_regular = df_regular.sort_values("sharpe", ascending=False)
        df_regular = df_regular.groupby("primary_field", group_keys=False).head(top_k_field)
        df_regular = df_regular.sort_values("sharpe", ascending=False)
        df_regular = df_regular.groupby("primary_op", group_keys=False).head(top_k_op)

        # 合并：分散后的 REGULAR + 全部 SuperAlpha
        df_result = pd.concat([df_regular, df_super], ignore_index=True)
        self.logger.info(f"Layer 3: 最终 {len(df_result)} 个 Alpha (REGULAR {len(df_regular)} + SuperAlpha {len(df_super)})")
        return df_result

    # ==================================================================
    # Pipeline 入口
    # ==================================================================
    def select(
        self,
        region: str,
        start_date: Optional[datetime] = None,
        delay: Optional[int] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        执行完整的三层粗筛 pipeline

        REGULAR 和 SUPER 分开获取：
        - REGULAR: API 过滤 margin>0.001
        - SUPER: API 过滤 sharpe>4 & fitness>4

        Args:
            region: 目标 region
            start_date: 创建日期下限
            delay: 可选 delay
            use_cache: 是否使用候选列表缓存

        Returns:
            筛选后的 DataFrame
        """
        # 分开获取 REGULAR 和 SUPER
        regular_df = self.fetch_candidates(region, start_date, delay, type_filter="REGULAR", use_cache=use_cache)
        super_df = self.fetch_candidates(region, start_date, delay, type_filter="SUPER", use_cache=use_cache)
        df = pd.concat([regular_df, super_df], ignore_index=True)

        if df.empty:
            return df

        df = self.apply_hard_filters(df)

        if len(df) < self.config["min_alpha_count"]:
            self.logger.warning("标准门槛不足，放宽重试")
            regular_df = self.fetch_candidates(region, start_date, delay, type_filter="REGULAR", use_cache=use_cache)
            super_df = self.fetch_candidates(region, start_date, delay, type_filter="SUPER", use_cache=use_cache)
            df = pd.concat([regular_df, super_df], ignore_index=True)
            df = self.apply_hard_filters(df, relaxed=True)

        if len(df) < self.config["min_alpha_count"]:
            self.logger.error(f"粗筛后仅 {len(df)} 个，不足门槛，终止")
            return df

        df = self.apply_correlation_filter(df)
        df = self.apply_diversification_filter(df)

        self.logger.info(f"{'='*50} 粗筛完成: {len(df)} 个 Alpha {'='*50}")
        return df

    # ==================================================================
    # 额外工具
    # ==================================================================
    def get_low_correlation_subset(
        self,
        df: pd.DataFrame,
        threshold: float = 0.7,
        max_size: int = 30,
        sort_by: str = "sharpe",
    ) -> pd.DataFrame:
        """基于 PnL 的 greedy max-clique 进一步精简"""
        if len(df) <= max_size:
            return df

        try:
            selected_ids = self.max_independent_alphas(df["id"].tolist(), threshold)
        except Exception as e:
            self.logger.error(f"max_independent_alphas 失败: {e}")
            return df

        if len(selected_ids) > max_size:
            score_map = dict(zip(df["id"], df[sort_by]))
            selected_ids = sorted(selected_ids, key=lambda x: score_map.get(x, 0), reverse=True)[:max_size]

        self.logger.info(f"低相关子集: {len(df)} -> {len(selected_ids)}")
        return df[df["id"].isin(selected_ids)].copy()

    def get_selected_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """获取筛选后 Alpha 的 returns 矩阵(供分配模型使用)"""
        if df.empty:
            return pd.DataFrame()
        try:
            returns = self.get_alpha_results(df["id"].tolist())
            self.logger.info(f"Returns 矩阵: {returns.shape}")
            return returns
        except Exception as e:
            self.logger.error(f"获取 returns 失败: {e}")
            return pd.DataFrame()
