import json
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from tqdm import tqdm
from wqb import FilterRange

from wqbkit.modules.correlation.alpha_calc_corr import AlphaCalcCorr
from wqbkit.app.config import config, DATA_DIR



class OsmosisAlphaSelectorV3(AlphaCalcCorr):
    """
    Osmosis V3 粗筛器 —— 在 V2 基础上增强质量评估维度

    继承链: OsmosisAlphaSelectorV3 -> AlphaCalcCorr -> AlphaDbCore -> AlphaBaseCore

    V3 增强点:
    - 扩展字段提取: os 指标、investabilityConstrained、selfCorrelation、dataset_tags、maxTrade
    - 年度稳定性评分: 通过 yearly-stats API 获取近 10 年表现
    - OS/IS 先验评分: 利用 osISSharpeRatio 或 investability proxy
    - Investability 衰减分类: 软过滤不降权排除
    - Diversification 增强: 增加 neutralization + dataset_tags 维度
    - MaxTrade 映射表: 持久化记录 MaxTradeOn simulation 状态
    """

    # ------------------------------------------------------------------
    # 默认配置
    # ------------------------------------------------------------------
    DEFAULT_CONFIG = {
        # --- Layer 1 [HardFilter]: Quality Gate (standard) ---
        "max_turnover": 20.0,
        "min_sharpe": 1.0,
        "min_fitness": 0.3,
        "max_drawdown": 25.0,
        "min_returns": 0.0,
        "require_returns_gt_drawdown": True,

        # --- Layer 1 [HardFilter]: Quality Gate (relaxed fallback) ---
        "relaxed_max_turnover": 25.0,
        "relaxed_min_sharpe": 0.8,
        "relaxed_min_fitness": 0.2,
        "relaxed_max_drawdown": 30.0,
        "relaxed_min_returns": 0.0,

        # --- Layer 2 [Investability]: Decay Check ---
        "investability_severe_threshold": 0.60,
        "investability_severe_multiplier": 0.2,
        "investability_moderate_threshold": 0.40,
        "investability_moderate_multiplier": 0.6,
        "investability_mild_threshold": 0.20,
        "investability_mild_multiplier": 0.85,

        # --- Layer 3 [Correlation]: PnL Correlation ---
        "pnl_corr_removal_threshold": 0.7,
        "high_corr_flag_threshold": 0.4,

        # --- Layer 3 [Correlation]: Drawdown Overlap ---
        "drawdown_overlap_threshold": 0.8,
        "drawdown_overlap_min_pnl_corr": 0.4,

        # --- Layer 3 [Correlation]: Prod Correlation Fallback ---
        "max_prod_corr": 0.7,

        # --- Layer 4 [Diversification]: Limits ---
        "div_neutralization_min": 5,
        "div_neutralization_max": 15,
        "div_neutralization_divisor": 15,
        "div_dataset_tag_min": 5,
        "div_dataset_tag_max": 20,
        "div_dataset_tag_divisor": 12,

        # --- Quality Score: IS Quality Weights ---
        "is_quality_fitness_weight": 0.23,
        "is_quality_sharpe_weight": 0.23,
        "is_quality_returns_weight": 0.14,
        "is_quality_margin_weight": 0.14,
        "is_quality_drawdown_weight": 0.10,
        "is_quality_turnover_weight": 0.08,
        "is_quality_balance_weight": 0.08,
        "is_quality_turnover_denom": 25.0,

        # --- Turnover Ideal Zone (from V1 oss2.py) ---
        "turnover_ideal_min": 8.0,
        "turnover_ideal_max": 20.0,
        "turnover_ideal_center": 14.0,
        "turnover_max_buffer_multiplier": 4.0,

        # --- Quality Score: Cost Quality Weights ---
        "cost_quality_margin_weight": 0.4,
        "cost_quality_turnover_weight": 0.3,
        "cost_quality_decay_weight": 0.3,
        "cost_quality_turnover_denom": 25.0,

        # --- Quality Score: Final Composition ---
        "quality_is_weight": 0.25,
        "quality_stability_weight": 0.25,
        "quality_cost_weight": 0.20,
        "quality_os_is_weight": 0.15,
        "quality_uniqueness_weight": 0.15,

        # --- Yearly Stability Score ---
        "yearly_min_records": 2,
        "yearly_min_is_records": 3,
        "yearly_min_sharpe_points": 2,
        "yearly_recent_window": 3,
        "yearly_trend_sigmoid_scale": 2.0,
        "yearly_weight_recent_sharpe": 0.35,
        "yearly_weight_positive_year": 0.25,
        "yearly_weight_sharpe_std": 0.20,
        "yearly_weight_trend": 0.20,

        # --- OS/IS Score ---
        "os_is_sigmoid_center": 0.5,
        "os_is_sigmoid_scale": 4.0,
        "os_is_proxy_penalty": 0.7,

        # --- Uniqueness Score ---
        "uniqueness_default_score": 0.5,
        "uniqueness_self_corr_fillna": 0.5,
        "uniqueness_prod_corr_fillna": 0.5,
        "uniqueness_pnl_corr_fillna": 0.5,

        # --- MaxTradeOn Post-Evaluation ---
        "maxtrade_eval_enabled": True,
        "maxtrade_on_ratio_excellent": 0.70,
        "maxtrade_on_ratio_good": 0.50,
        "maxtrade_on_ratio_acceptable": 0.30,
        "maxtrade_on_adj_excellent": 1.0,
        "maxtrade_on_adj_good": 0.70,
        "maxtrade_on_adj_acceptable": 0.40,
        "maxtrade_on_adj_poor": 0.15,
        "maxtrade_on_adj_no_sim": 0.85,

        # --- API Fetching ---
        "api_margin_threshold_low": 0.001,
        "api_margin_threshold_high": 0.0015,
        "api_margin_low_regions": ("USA", "EUR"),
        "api_super_min_sharpe": 4.0,
        "api_super_min_fitness": 4.0,

        # --- General ---
        "min_alpha_count": 10,
        "maxtrade_log_batch": 10,
        "low_correlation_subset_threshold": 0.7,
        "low_correlation_subset_max_size": 30,
    }

    CACHE_TTL_MINUTES = 60
    YEARLY_STATS_CACHE_TTL_HOURS = 24
    API_BASE_URL = config.WQB_API_BASE_URL

    # ------------------------------------------------------------------
    # 数据目录定位
    # ------------------------------------------------------------------
    @staticmethod
    def _get_data_dir() -> Path:
        """Osmosis V3 统一数据目录"""
        data_dir = DATA_DIR / "Osmosis"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def __init__(self, config: Optional[Dict] = None):
        super().__init__()
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        data_dir = self._get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        # 缓存与黑名单目录
        self.cache_dir = data_dir / "selector_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # yearly-stats 缓存目录
        self.yearly_stats_dir = data_dir / "yearly_stats_cache"
        self.yearly_stats_dir.mkdir(parents=True, exist_ok=True)

        # MaxTrade 映射表
        self.maxtrade_path = data_dir / "maxtrade_status.json"
        self.maxtrade_map: Dict[str, Dict] = self._load_maxtrade_map()

        # 黑名单
        self.blacklist_path = self.cache_dir / "blacklist.json"
        self.blacklist: set = self._load_blacklist()

        self.logger.info(
            f"OsmosisAlphaSelectorV3 init: blacklist={len(self.blacklist)} items, "
            f"maxtrade_map={len(self.maxtrade_map)} items, "
            f"cache_dir={self.cache_dir}"
        )

    # ==================================================================
    # 黑名单管理（继承 V2）
    # ==================================================================
    def _load_blacklist(self) -> set:
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
        try:
            with open(self.blacklist_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"alpha_ids": sorted(list(self.blacklist)), "updated_at": datetime.now().isoformat()},
                    f, indent=2,
                )
        except Exception as e:
            self.logger.error(f"保存黑名单失败: {e}")

    def add_to_blacklist(self, alpha_ids: Union[str, List[str]], reason: str = "") -> None:
        if isinstance(alpha_ids, str):
            alpha_ids = [alpha_ids]
        alpha_ids = [aid for aid in alpha_ids if aid]
        if not alpha_ids:
            return
        self.blacklist.update(alpha_ids)
        self._save_blacklist()
        self.logger.info(f"Blacklist +{len(alpha_ids)} (reason={reason})")

    def remove_from_blacklist(self, alpha_ids: Union[str, List[str]]) -> None:
        if isinstance(alpha_ids, str):
            alpha_ids = [alpha_ids]
        alpha_ids = [aid for aid in alpha_ids if aid in self.blacklist]
        if not alpha_ids:
            return
        self.blacklist.difference_update(alpha_ids)
        self._save_blacklist()
        self.logger.info(f"Blacklist -{len(alpha_ids)}: {alpha_ids}")

    def clear_blacklist(self) -> None:
        count = len(self.blacklist)
        self.blacklist.clear()
        self._save_blacklist()
        self.logger.info(f"Blacklist cleared ({count} items)")

    def is_blacklisted(self, alpha_id: str) -> bool:
        return alpha_id in self.blacklist

    def list_blacklist(self) -> List[str]:
        return sorted(list(self.blacklist))

    # ==================================================================
    # MaxTrade 映射表管理（V3 新增）
    # ==================================================================
    def _load_maxtrade_map(self) -> Dict[str, Dict]:
        if not self.maxtrade_path.exists():
            return {}
        try:
            with open(self.maxtrade_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载 MaxTrade 映射表失败: {e}")
            return {}

    def _save_maxtrade_map(self) -> None:
        try:
            with open(self.maxtrade_path, "w", encoding="utf-8") as f:
                json.dump(self.maxtrade_map, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存 MaxTrade 映射表失败: {e}")

    def update_maxtrade_status(
        self,
        alpha_id: str,
        has_maxTradeOn_sim: bool,
        maxTradeOn_sharpe: Optional[float] = None,
        maxTradeOn_fitness: Optional[float] = None,
        new_alpha_id: Optional[str] = None,
        notes: str = "",
    ) -> None:
        """用户手动完成 MaxTradeOn simulation 后调用此接口更新"""
        self.maxtrade_map[alpha_id] = {
            "has_maxTradeOn_sim": has_maxTradeOn_sim,
            "maxTradeOn_sharpe": maxTradeOn_sharpe,
            "maxTradeOn_fitness": maxTradeOn_fitness,
            "new_alpha_id": new_alpha_id,
            "updated_at": datetime.now().isoformat(),
            "notes": notes,
        }
        self._save_maxtrade_map()
        self.logger.info(f"MaxTrade 映射表更新: {alpha_id} -> {has_maxTradeOn_sim}")

    def get_maxtrade_status(self, alpha_id: str) -> Dict:
        return self.maxtrade_map.get(alpha_id, {"has_maxTradeOn_sim": False})

    # ==================================================================
    # 缓存管理（继承 V2 + 新增 yearly_stats 缓存）
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

    # --- yearly-stats 缓存 ---
    def _yearly_stats_cache_path(self, alpha_id: str) -> Path:
        return self.yearly_stats_dir / f"{alpha_id}.json"

    def _load_yearly_stats_cache(self, alpha_id: str, max_age_hours: int = 24) -> Optional[List[Dict]]:
        path = self._yearly_stats_cache_path(alpha_id)
        if not path.exists():
            return None
        try:
            if time.time() - path.stat().st_mtime > max_age_hours * 3600:
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_yearly_stats_cache(self, alpha_id: str, data: List[Dict]) -> None:
        path = self._yearly_stats_cache_path(alpha_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"yearly-stats 缓存保存失败: {e}")

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
                margin_threshold = (
                    self.config["api_margin_threshold_low"]
                    if region in self.config["api_margin_low_regions"]
                    else self.config["api_margin_threshold_high"]
                )
                filters["margin"] = FilterRange.from_str(f"[{margin_threshold}, inf)")
            elif type_filter == 'SUPER':
                filters["sharpe"] = FilterRange.from_str(f"[{self.config['api_super_min_sharpe']}, inf)")
                filters["fitness"] = FilterRange.from_str(f"[{self.config['api_super_min_fitness']}, inf)")

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
        os_data = item.get("os", {}) or {}
        inv = is_data.get("investabilityConstrained", {}) or {}

        # --- V2 已有字段 ---
        result = {
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
            "prodCorrelation": is_data.get("prodCorrelation"),
            "selfCorrelation": is_data.get("selfCorrelation"),
        }

        # --- V3 新增字段 ---
        result.update({
            # OS 指标（可能为 None）
            "os_sharpe": os_data.get("sharpe"),
            "os_fitness": os_data.get("fitness"),
            "os_returns": os_data.get("returns"),
            "os_drawdown": os_data.get("drawdown"),
            "os_turnover": os_data.get("turnover"),
            "os_margin": os_data.get("margin"),
            "os_is_ratio": os_data.get("osISSharpeRatio"),

            # Investability 约束后指标（始终存在）
            "inv_sharpe": inv.get("sharpe"),
            "inv_fitness": inv.get("fitness"),
            "inv_returns": inv.get("returns"),
            "inv_drawdown": inv.get("drawdown"),
            "inv_turnover": inv.get("turnover"),
            "inv_margin": inv.get("margin"),

            # MaxTrade
            "max_trade": settings.get("maxTrade", "OFF"),

            # Dataset 类别（完整 tags 列表，支持多标签）
            "dataset_tags": item.get("tags", ["unknown"]) if item.get("tags") else ["unknown"],

            # 完整 settings 和 regular（用于重新 simulation）
            "settings_full": settings,
            "regular_full": item.get("regular", {}),
        })

        return result

    def fetch_candidates(
        self,
        region: str,
        start_date: Optional[datetime] = None,
        delay: Optional[int] = None,
        type_filter: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取候选 Alpha，支持缓存与黑名单过滤"""
        cache_key = f"{region}_{delay or 'any'}_{type_filter}"

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

        # 黑名单过滤
        before = len(df)
        df = df[~df["id"].isin(self.blacklist)].copy()
        removed = before - len(df)
        if removed:
            self.logger.info(f"Blacklist filtered: -{removed}")

        # 本地过滤 start_date
        if start_date:
            df["dateCreated"] = pd.to_datetime(df["dateCreated"], errors="coerce", utc=True).dt.tz_localize(None)
            start_date_naive = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
            df = df[df["dateCreated"] >= start_date_naive].copy()

        self.logger.info(f"fetch_candidates: 最终返回 {len(df)} 个 Alpha")
        return df


    # ==================================================================
    # yearly-stats 获取（V3 新增）
    # ==================================================================
    def _fetch_yearly_stats_single(self, alpha_id: str) -> Optional[List[Dict]]:
        """获取单个 Alpha 的 yearly-stats，带缓存"""
        # 1. 检查缓存
        cached = self._load_yearly_stats_cache(alpha_id, self.YEARLY_STATS_CACHE_TTL_HOURS)
        if cached is not None:
            return cached

        # 2. 调用 API
        url = f"{self.API_BASE_URL}/alphas/{alpha_id}/recordsets/yearly-stats"
        try:
            resp = self.get(url)
            data = resp.json()

            # 解析 schema.properties + records（二维数组）
            properties = [p["name"] for p in data.get("schema", {}).get("properties", [])]
            records = []
            for row in data.get("records", []):
                record = dict(zip(properties, row))
                # 类型转换
                record["year"] = int(record["year"]) if record.get("year") else None
                for num_col in ["sharpe", "returns", "drawdown", "fitness", "turnover", "margin"]:
                    if record.get(num_col) is not None:
                        record[num_col] = float(record[num_col])
                records.append(record)

            # 保存缓存
            self._save_yearly_stats_cache(alpha_id, records)
            return records
        except Exception as e:
            self.logger.warning(f"获取 yearly-stats 失败 {alpha_id}: {e}")
            return None

    def fetch_yearly_stats_batch(
        self,
        alpha_ids: List[str],
        max_workers: int = 8,
    ) -> Dict[str, List[Dict]]:
        """
        批量获取 yearly-stats，使用 ThreadPool 并发
        返回: {alpha_id: [yearly_record, ...]}
        """
        results = {}
        # 先读缓存
        to_fetch = []
        for aid in alpha_ids:
            cached = self._load_yearly_stats_cache(aid, self.YEARLY_STATS_CACHE_TTL_HOURS)
            if cached is not None:
                results[aid] = cached
            else:
                to_fetch.append(aid)

        if not to_fetch:
            self.logger.info(f"yearly-stats: 全部 {len(alpha_ids)} 个从缓存命中")
            return results

        self.logger.info(f"yearly-stats: 缓存命中 {len(results)} 个，需获取 {len(to_fetch)} 个")

        # 并发获取
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {executor.submit(self._fetch_yearly_stats_single, aid): aid for aid in to_fetch}
            for future in tqdm(as_completed(future_to_id), total=len(to_fetch), desc="yearly-stats"):
                aid = future_to_id[future]
                try:
                    data = future.result()
                    if data is not None:
                        results[aid] = data
                except Exception as e:
                    self.logger.warning(f"yearly-stats 并发获取失败 {aid}: {e}")

        return results

    # ==================================================================
    # 评分计算（V3 新增）
    # ==================================================================
    @staticmethod
    def _sigmoid(x: float) -> float:
        """Sigmoid 函数，映射到 (0, 1)"""
        return 1.0 / (1.0 + np.exp(-x))

    @staticmethod
    def _rank_normalize(series: pd.Series) -> pd.Series:
        """Rankdata 标准化到 [0, 1]"""
        from scipy.stats import rankdata
        if series.nunique() <= 1 or len(series) <= 1:
            return pd.Series(0.5, index=series.index)
        return pd.Series(rankdata(series.fillna(series.min())) / len(series), index=series.index)

    def _calculate_turnover_score(self, turnover: float) -> float:
        """
        Turnover 理想区间评分 [0, 1]
        来自 V1 oss2.py 的分段函数：
        - 理想区间 [turnover_ideal_min, turnover_ideal_max] 得高分
        - turnover_ideal_center 处满分
        - 低于理想区间线性衰减，高于理想区间快速衰减
        """
        cfg = self.config
        if pd.isna(turnover):
            return 0.5
        ideal_min = cfg["turnover_ideal_min"]
        ideal_max = cfg["turnover_ideal_max"]
        ideal_center = cfg["turnover_ideal_center"]
        buffer_mult = cfg["turnover_max_buffer_multiplier"]

        if ideal_min <= turnover <= ideal_max:
            distance = abs(turnover - ideal_center) / (ideal_max - ideal_min)
            score = 1.0 - distance
        elif turnover < ideal_min:
            score = max(0, turnover / ideal_min)
        else:
            score = max(
                0,
                1.0 - (turnover - ideal_max) / (buffer_mult * ideal_max)
                if ideal_max > 0 else 0
            )
        return max(0.0, min(1.0, score))

    def _calculate_balance_score(self, long_count: float, short_count: float) -> float:
        """
        多空平衡评分 [0, 1]
        来自 V1 oss2.py：
        - min(long, short) / max(long, short) 开根号
        - 完全不平衡（一方为0）得 0.2
        - 完全平衡得 1.0
        """
        if pd.isna(long_count) or pd.isna(short_count):
            return 0.5
        if long_count == 0 and short_count == 0:
            return 0.0
        if long_count == 0 or short_count == 0:
            return 0.2
        ratio = min(long_count, short_count) / max(long_count, short_count)
        balance_score = ratio ** 0.5 if ratio >= 0 else 0
        return min(1.0, max(0.0, balance_score))

    def _compute_yearly_stability_score(self, yearly_stats_list: List[Dict]) -> float:
        """
        计算年度稳定性评分 [0, 1]
        优先使用 IS 阶段数据，要求至少 2 年 sharpe 数据
        """
        cfg = self.config
        if not yearly_stats_list or len(yearly_stats_list) < cfg["yearly_min_records"]:
            return cfg["uniqueness_default_score"]

        # 优先使用 IS 阶段记录
        is_records = [s for s in yearly_stats_list if s.get("stage") == "IS"]
        records = is_records if len(is_records) >= cfg["yearly_min_is_records"] else yearly_stats_list

        sharpe_list = [s["sharpe"] for s in records if s.get("sharpe") is not None]
        if len(sharpe_list) < cfg["yearly_min_sharpe_points"]:
            return cfg["uniqueness_default_score"]

        recent_window = cfg["yearly_recent_window"]
        recent_sharpe_mean = np.mean(sharpe_list[-recent_window:]) if len(sharpe_list) >= recent_window else np.mean(sharpe_list)
        positive_year_ratio = sum(1 for s in sharpe_list if s > 0) / len(sharpe_list)
        sharpe_std = np.std(sharpe_list)

        # 最近趋势：最后一年 vs 前一年的变化方向
        if len(sharpe_list) >= 2:
            trend = (sharpe_list[-1] - sharpe_list[-2]) / (abs(sharpe_list[-2]) + 1e-6)
            trend_score = self._sigmoid(trend * cfg["yearly_trend_sigmoid_scale"])
        else:
            trend_score = cfg["uniqueness_default_score"]

        # 归一化 helper
        def _norm(val, vals):
            mn, mx = min(vals), max(vals)
            if mx <= mn:
                return cfg["uniqueness_default_score"]
            return (val - mn) / (mx - mn)

        score = (
            cfg["yearly_weight_recent_sharpe"] * _norm(recent_sharpe_mean, sharpe_list) +
            cfg["yearly_weight_positive_year"] * positive_year_ratio +
            cfg["yearly_weight_sharpe_std"] * _norm(-sharpe_std, [-s for s in sharpe_list]) +
            cfg["yearly_weight_trend"] * trend_score
        )
        return float(np.clip(score, 0, 1))

    def _compute_os_is_score(self, row: pd.Series) -> float:
        """OS/IS 先验评分 [0, 1]，优先使用现成的 osISSharpeRatio"""
        cfg = self.config
        os_is_ratio = row.get("os_is_ratio")
        if pd.notna(os_is_ratio):
            return float(
                self._sigmoid(
                    (os_is_ratio - cfg["os_is_sigmoid_center"]) * cfg["os_is_sigmoid_scale"]
                )
            )

        # 无 osISSharpeRatio 时，用 inv_sharpe / is_sharpe 代理
        inv_sharpe = row.get("inv_sharpe")
        is_sharpe = row.get("sharpe", 0)
        if pd.notna(inv_sharpe) and is_sharpe > 0:
            proxy_ratio = inv_sharpe / is_sharpe
            return float(
                self._sigmoid(
                    (proxy_ratio - cfg["os_is_sigmoid_center"]) * cfg["os_is_sigmoid_scale"]
                )
                * cfg["os_is_proxy_penalty"]
            )

        return cfg["uniqueness_default_score"]

    def _compute_investability_decay(self, row: pd.Series) -> Tuple[str, float]:
        """
        计算 investability 衰减分类和降权系数
        返回: (decay_label, weight_multiplier)
        """
        is_sharpe = row.get("sharpe", 0)
        inv_sharpe = row.get("inv_sharpe")

        if is_sharpe <= 0 or pd.isna(inv_sharpe):
            return "unknown", 1.0

        decay = (is_sharpe - inv_sharpe) / is_sharpe

        cfg = self.config
        if decay >= cfg["investability_severe_threshold"]:
            return "severe_decay", cfg["investability_severe_multiplier"]
        elif decay >= cfg["investability_moderate_threshold"]:
            return "moderate_decay", cfg["investability_moderate_multiplier"]
        elif decay >= cfg["investability_mild_threshold"]:
            return "mild_decay", cfg["investability_mild_multiplier"]
        else:
            return "stable", 1.0

    def _compute_maxtrade_adjustment(self, df: pd.DataFrame) -> pd.Series:
        """
        MaxTradeOn 后评估调整因子 [0, 1]

        基于 MaxTradeOn simulation 后的 sharpe 与 IS sharpe 的比率，
        评估 Alpha 在更严格交易条件下的稳健性。

        返回: 调整因子 Series，quality_score 将乘以该因子
        """
        cfg = self.config
        if not cfg["maxtrade_eval_enabled"]:
            return pd.Series(1.0, index=df.index)

        adjustments = []
        for _, row in df.iterrows():
            if row.get("max_trade") == "ON":
                # 当前已经是 MaxTradeOn，IS 数据即真实表现
                adjustments.append(cfg["maxtrade_on_adj_excellent"])
                continue

            # max_trade == "OFF"，检查映射表
            status = self.get_maxtrade_status(row["id"])
            if status.get("has_maxTradeOn_sim"):
                on_sharpe = status.get("maxTradeOn_sharpe")
                is_sharpe = row.get("sharpe", 0)

                if (
                    is_sharpe is not None
                    and is_sharpe > 0
                    and on_sharpe is not None
                    and on_sharpe > 0
                ):
                    ratio = on_sharpe / is_sharpe
                    if ratio >= cfg["maxtrade_on_ratio_excellent"]:
                        adjustments.append(cfg["maxtrade_on_adj_excellent"])
                    elif ratio >= cfg["maxtrade_on_ratio_good"]:
                        adjustments.append(cfg["maxtrade_on_adj_good"])
                    elif ratio >= cfg["maxtrade_on_ratio_acceptable"]:
                        adjustments.append(cfg["maxtrade_on_adj_acceptable"])
                    else:
                        adjustments.append(cfg["maxtrade_on_adj_poor"])
                else:
                    # MaxTradeOn 后 sharpe <= 0 或 IS sharpe <= 0
                    adjustments.append(cfg["maxtrade_on_adj_poor"])
            else:
                # 无 MaxTradeOn sim 记录，不确定性
                adjustments.append(cfg["maxtrade_on_adj_no_sim"])

        return pd.Series(adjustments, index=df.index)

    def _compute_uniqueness_score(self, df: pd.DataFrame) -> pd.Series:
        """
        独特性评分 [0, 1]，基于 selfCorrelation、prodCorrelation 和 PnL correlation 均值
        越低的相关性 = 越高的独特性
        """
        cfg = self.config
        default_score = cfg["uniqueness_default_score"]
        scores = pd.Series(default_score, index=df.index)
        count = 0

        # 1. selfCorrelation: 越低越好
        if "selfCorrelation" in df.columns:
            self_corr = df["selfCorrelation"].fillna(cfg["uniqueness_self_corr_fillna"])
            self_score = 1.0 - self_corr.clip(0, 1)
            scores = self_score
            count += 1

        # 2. prodCorrelation: 越低越好
        if "prodCorrelation" in df.columns:
            prod_corr = df["prodCorrelation"].fillna(cfg["uniqueness_prod_corr_fillna"])
            prod_score = 1.0 - prod_corr.clip(0, 1)
            scores = (scores * count + prod_score) / (count + 1) if count > 0 else prod_score
            count += 1

        # 3. PnL correlation 均值: 越低越好 (V3 新增)
        if "pnl_corr_mean" in df.columns:
            pnl_mean = df["pnl_corr_mean"].fillna(cfg["uniqueness_pnl_corr_fillna"])
            pnl_score = 1.0 - pnl_mean.clip(0, 1)
            scores = (scores * count + pnl_score) / (count + 1) if count > 0 else pnl_score
            count += 1

        # rank-normalize
        return self._rank_normalize(scores)

    def _compute_all_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        统一计算所有 V3 评分，添加到 DataFrame
        需要在 fetch_yearly_stats_batch 之后调用
        """
        if df.empty:
            return df

        df = df.copy()

        cfg = self.config
        default_score = cfg["uniqueness_default_score"]

        # 1. 年度稳定性评分（需要 yearly_stats 列已存在）
        if "yearly_stats" in df.columns:
            df["yearly_stability"] = df["yearly_stats"].apply(
                lambda x: self._compute_yearly_stability_score(x) if isinstance(x, list) else default_score
            )
        else:
            df["yearly_stability"] = default_score

        # 2. OS/IS 先验评分
        df["os_is_score"] = df.apply(self._compute_os_is_score, axis=1)

        # 3. Investability 衰减
        decay_results = df.apply(self._compute_investability_decay, axis=1)
        df["decay_label"] = decay_results.apply(lambda x: x[0])
        df["decay_multiplier"] = decay_results.apply(lambda x: x[1])

        # 4. 独特性评分
        df["uniqueness_score"] = self._compute_uniqueness_score(df)

        # 5. MaxTradeOn 后评估调整因子
        df["maxtrade_adjustment"] = self._compute_maxtrade_adjustment(df)

        # 6. Turnover 理想区间评分 & Balance 评分（来自 V1 oss2.py）
        df["turnover_score"] = df["turnover"].apply(self._calculate_turnover_score)
        df["balance_score"] = df.apply(
            lambda r: self._calculate_balance_score(
                r.get("longCount", 0), r.get("shortCount", 0)
            ), axis=1
        )

        # 7. 综合 quality_score（五维结构）
        # IS 质量 = fitness, sharpe, returns, margin, drawdown, turnover, balance 的 rank-normalized 加权
        is_quality = (
            cfg["is_quality_fitness_weight"] * self._rank_normalize(df["fitness"]) +
            cfg["is_quality_sharpe_weight"] * self._rank_normalize(df["sharpe"]) +
            cfg["is_quality_returns_weight"] * self._rank_normalize(df["returns"]) +
            cfg["is_quality_margin_weight"] * self._rank_normalize(df["margin"]) +
            cfg["is_quality_drawdown_weight"] * self._rank_normalize(-df["drawdown"].fillna(0)) +
            cfg["is_quality_turnover_weight"] * df["turnover_score"] +
            cfg["is_quality_balance_weight"] * df["balance_score"]
        )

        # Cost quality = margin 高 + turnover 理想 + investability 稳定
        cost_quality = (
            cfg["cost_quality_margin_weight"] * self._rank_normalize(df["margin"]) +
            cfg["cost_quality_turnover_weight"] * df["turnover_score"] +
            cfg["cost_quality_decay_weight"] * df["decay_multiplier"]
        )

        df["quality_score"] = (
            cfg["quality_is_weight"] * is_quality +
            cfg["quality_stability_weight"] * df["yearly_stability"] +
            cfg["quality_cost_weight"] * cost_quality +
            cfg["quality_os_is_weight"] * df["os_is_score"] +
            cfg["quality_uniqueness_weight"] * df["uniqueness_score"]
        ) * df["maxtrade_adjustment"]

        # 归一化到 [0, 1]
        if df["quality_score"].nunique() > 1:
            qmin, qmax = df["quality_score"].min(), df["quality_score"].max()
            if qmax > qmin:
                df["quality_score"] = (df["quality_score"] - qmin) / (qmax - qmin)
        else:
            df["quality_score"] = 0.5

        if "max_trade" in df.columns:
            n_on = (df["max_trade"] == "ON").sum()
            n_off_no_sim = ((df["max_trade"] == "OFF") & (df["maxtrade_adjustment"] == cfg["maxtrade_on_adj_no_sim"])).sum()
            n_off_poor = ((df["max_trade"] == "OFF") & (df["maxtrade_adjustment"] <= cfg["maxtrade_on_adj_poor"])).sum()
        else:
            n_on = n_off_no_sim = n_off_poor = 0
        self.logger.info(
            f"评分计算完成: stability={df['yearly_stability'].mean():.3f}, "
            f"os_is={df['os_is_score'].mean():.3f}, "
            f"maxtrade_adj={df['maxtrade_adjustment'].mean():.3f} "
            f"(ON={n_on}, OFF无sim={n_off_no_sim}, OFF差={n_off_poor}), "
            f"quality={df['quality_score'].mean():.3f}"
        )
        return df

    # ==================================================================
    # 筛选层
    # ==================================================================
    def apply_hard_filters(self, df: pd.DataFrame, relaxed: bool = False) -> pd.DataFrame:
        """Layer 1 [HardFilter]: 硬性质量门槛（继承 V2）"""
        if df.empty:
            return df

        cfg = self.config

        if not relaxed:
            mask = (
                (df["turnover"] < cfg["max_turnover"]) &
                (df["sharpe"] > cfg["min_sharpe"]) &
                (df["fitness"] > cfg["min_fitness"]) &
                (df["drawdown"].abs() < cfg["max_drawdown"]) &
                (df["returns"] > cfg["min_returns"])
            )
            if cfg["require_returns_gt_drawdown"]:
                mask = mask & (df["returns"] > df["drawdown"].abs())
            label = "标准"
        else:
            mask = (
                (df["turnover"] < cfg["relaxed_max_turnover"]) &
                (df["sharpe"] > cfg["relaxed_min_sharpe"]) &
                (df["fitness"] > cfg["relaxed_min_fitness"]) &
                (df["drawdown"].abs() < cfg["relaxed_max_drawdown"]) &
                (df["returns"] > cfg["relaxed_min_returns"])
            )
            if cfg["require_returns_gt_drawdown"]:
                mask = mask & (df["returns"] > df["drawdown"].abs())
            label = "放宽"

        filtered = df[mask].copy()
        self.logger.info(f"Layer 1 [HardFilter] ({label}): {len(df)} -> {len(filtered)}")
        return filtered

    def apply_investability_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 2 [Investability]: 可投资性软检查（V3 新增）
        - 不自动排除衰减严重的 Alpha
        - 标记 decay_label，在 quality_score 中已通过 decay_multiplier 降权
        - 日志输出需要人工复核的 Alpha
        """
        if df.empty:
            return df

        severe = df[df["decay_label"] == "severe_decay"]
        moderate = df[df["decay_label"] == "moderate_decay"]

        if len(severe) > 0:
            self.logger.warning(
                f"Layer 2 [Investability]: {len(severe)} 个 Alpha 衰减严重(≥60%)，"
                f"已在 quality_score 中大幅降权，建议人工复核: {severe['id'].tolist()}"
            )
        if len(moderate) > 0:
            self.logger.info(
                f"Layer 2 [Investability]: {len(moderate)} 个 Alpha 中度衰减(40-60%)，"
                f"IDs: {moderate['id'].tolist()}"
            )

        # MaxTradeOn 状态检查
        maxtrade_off = df[df["max_trade"] == "OFF"]
        needs_resim = []
        poor_after_on = []
        for _, row in maxtrade_off.iterrows():
            status = self.get_maxtrade_status(row["id"])
            if not status.get("has_maxTradeOn_sim", False):
                needs_resim.append(row["id"])
            else:
                on_sharpe = status.get("maxTradeOn_sharpe")
                is_sharpe = row.get("sharpe", 0)
                if is_sharpe > 0 and on_sharpe is not None and on_sharpe > 0:
                    ratio = on_sharpe / is_sharpe
                    if ratio < self.config["maxtrade_on_ratio_acceptable"]:
                        poor_after_on.append(f"{row['id']}(ratio={ratio:.1%})")
                elif on_sharpe is not None and on_sharpe <= 0:
                    poor_after_on.append(f"{row['id']}(sharpe≤0)")

        if needs_resim:
            self.logger.warning(
                f"Layer 2 [Investability]: {len(needs_resim)} 个 Alpha maxTrade=OFF 且无 MaxTradeOn simulation 记录，"
                f"quality_score 已降权({self.config['maxtrade_on_adj_no_sim']}×)，"
                f"建议重新 simulation 后更新映射表。IDs: {needs_resim[:10]}{'...' if len(needs_resim) > 10 else ''}"
            )
        if poor_after_on:
            self.logger.warning(
                f"Layer 2 [Investability]: {len(poor_after_on)} 个 Alpha MaxTradeOn 后表现极差(比率<{self.config['maxtrade_on_ratio_acceptable']:.0%})，"
                f"quality_score 已大幅降权，建议人工复核: {poor_after_on[:10]}{'...' if len(poor_after_on) > 10 else ''}"
            )

        return df

    # ==================================================================
    # Layer 3 [Correlation] 辅助方法 (PnL correlation + drawdown overlap)
    # ==================================================================
    def _compute_drawdown_mask(self, returns: pd.DataFrame) -> pd.DataFrame:
        """计算每个 Alpha 的回撤期掩码（True 表示在回撤中）"""
        cum_pnl = returns.fillna(0).cumsum()
        running_max = cum_pnl.expanding().max()
        drawdown = cum_pnl - running_max
        return drawdown < 0

    def _filter_by_pnl_corr(self, df: pd.DataFrame, pnl_corr: pd.DataFrame, score_col: str) -> pd.DataFrame:
        """基于 PnL correlation 过滤，标记 high_corr_flag (0.4~0.7)"""
        df = df.copy()
        if "high_corr_flag" not in df.columns:
            df["high_corr_flag"] = False
        to_remove = set()
        sorted_df = df.sort_values(score_col, ascending=False)

        for _, row_i in sorted_df.iterrows():
            aid_i = row_i["id"]
            type_i = row_i.get("type", "REGULAR")
            if aid_i in to_remove:
                continue
            for _, row_j in sorted_df.iterrows():
                aid_j = row_j["id"]
                type_j = row_j.get("type", "REGULAR")
                if aid_i == aid_j or aid_j in to_remove:
                    continue
                # 单向处理：高分保留，低分淘汰
                if row_i[score_col] < row_j[score_col]:
                    continue

                # 方案 B: SuperAlpha 与 REGULAR 之间不淘汰
                if (type_i == "SUPER" and type_j == "REGULAR") or (type_i == "REGULAR" and type_j == "SUPER"):
                    continue

                corr_val = (
                    pnl_corr.loc[aid_i, aid_j]
                    if aid_i in pnl_corr.index and aid_j in pnl_corr.columns
                    else None
                )
                if pd.isna(corr_val):
                    continue

                if corr_val > self.config["pnl_corr_removal_threshold"]:
                    to_remove.add(aid_j)
                elif corr_val >= self.config["high_corr_flag_threshold"]:
                    df.loc[df["id"] == aid_i, "high_corr_flag"] = True
                    df.loc[df["id"] == aid_j, "high_corr_flag"] = True

        df_filtered = df[~df["id"].isin(to_remove)].copy()
        removed_df = df[df["id"].isin(to_remove)]
        if "type" in removed_df.columns and not removed_df.empty:
            n_removed_super = (removed_df["type"] == "SUPER").sum()
            n_removed_regular = len(removed_df) - n_removed_super
        else:
            n_removed_super = 0
            n_removed_regular = len(removed_df)
        self.logger.info(
            f"Layer 3 [Correlation]: {len(df)} -> {len(df_filtered)} 个 "
            f"(淘汰 {len(to_remove)} 个: REGULAR={n_removed_regular}, SUPER={n_removed_super}, "
            f"high_corr_flag={df_filtered['high_corr_flag'].sum()} 个)"
        )
        return df_filtered

    def _find_drawdown_overlap_pairs(
        self,
        dd_mask: pd.DataFrame,
        df: pd.DataFrame,
        score_col: str,
        threshold: float = 0.4,
        pnl_corr: Optional[pd.DataFrame] = None,
        min_pnl_corr: float = 0.4,
    ) -> set:
        """
        找出 drawdown overlap > threshold 的 pair，返回应淘汰的 id 集合

        修复黑洞效应:
        - 分母从 min 改为 max，避免长回撤期 Alpha 吞噬所有其他 Alpha
        - 只检查 PnL correlation > min_pnl_corr 的 pair，低相关的不需要查
        """
        to_remove = set()
        sorted_df = df.sort_values(score_col, ascending=False)
        cols = dd_mask.columns.tolist()

        for _, row_i in sorted_df.iterrows():
            aid_i = row_i["id"]
            type_i = row_i.get("type", "REGULAR")
            if aid_i in to_remove or aid_i not in cols:
                continue
            for _, row_j in sorted_df.iterrows():
                aid_j = row_j["id"]
                type_j = row_j.get("type", "REGULAR")
                if aid_i == aid_j or aid_j in to_remove or aid_j not in cols:
                    continue
                # 单向处理：高分保留，低分淘汰
                if row_i[score_col] < row_j[score_col]:
                    continue

                # 方案 B: SuperAlpha 与 REGULAR 之间不淘汰
                if (type_i == "SUPER" and type_j == "REGULAR") or (type_i == "REGULAR" and type_j == "SUPER"):
                    continue

                # 跳过 PnL correlation 过低的 pair（无意义检查）
                corr_val = None
                if pnl_corr is not None:
                    corr_val = (
                        pnl_corr.loc[aid_i, aid_j]
                        if aid_i in pnl_corr.index and aid_j in pnl_corr.columns
                        else None
                    )
                    if pd.isna(corr_val) or abs(corr_val) < min_pnl_corr:
                        continue

                both_in_dd = (dd_mask[aid_i] & dd_mask[aid_j]).sum()
                max_dd = max(dd_mask[aid_i].sum(), dd_mask[aid_j].sum())
                if max_dd == 0:
                    continue
                overlap = both_in_dd / max_dd
                if overlap > threshold:
                    to_remove.add(aid_j)

        return to_remove

    def _filter_by_prod_corr_fallback(self, df: pd.DataFrame) -> pd.DataFrame:
        """V2 fallback: 基于 prodCorrelation 的过滤"""
        threshold = self.config["max_prod_corr"]
        has_prod_corr = df["prodCorrelation"].notna().sum()

        if has_prod_corr == len(df):
            df["prod_corr"] = df["prodCorrelation"]
            self.logger.info(f"Layer 3 [Correlation] [prod fallback]: 内置 prodCorrelation ({len(df)} 个)")
        elif has_prod_corr > 0:
            missing_ids = df[df["prodCorrelation"].isna()]["id"].tolist()
            self.logger.info(f"Layer 3 [Correlation] [prod fallback]: {has_prod_corr} 内置, {len(missing_ids)} 调 API")
            try:
                corr_results = self.calculate(missing_ids, calc_type="prod")
                df["prod_corr"] = df.apply(
                    lambda row: row["prodCorrelation"]
                    if pd.notna(row["prodCorrelation"])
                    else corr_results.get(row["id"], 1.0),
                    axis=1,
                )
            except Exception as e:
                self.logger.error(f"补充 prodCorrelation 失败: {e}，跳过 fallback")
                return df
        else:
            self.logger.info(f"Layer 3 [Correlation] [prod fallback]: 调 API 计算 {len(df)} 个")
            try:
                corr_results = self.calculate(df["id"].tolist(), calc_type="prod")
                df["prod_corr"] = df["id"].map(lambda aid: corr_results.get(aid, 1.0))
            except Exception as e:
                self.logger.error(f"prodCorrelation 过滤失败: {e}，跳过 fallback")
                return df

        df_pass = df[df["prod_corr"] < threshold].copy()
        self.logger.info(f"Layer 3 [Correlation] [prod fallback]: {len(df)} -> {len(df_pass)} 个")
        return df_pass.drop(columns=["prod_corr"], errors="ignore")

    def apply_correlation_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 3 [Correlation]: PnL correlation + drawdown overlap 过滤"""
        if df.empty or len(df) <= self.config["min_alpha_count"]:
            df = df.copy()
            df["high_corr_flag"] = False
            return df

        original_df = df.copy()
        df_work = df.copy()
        df_work["high_corr_flag"] = False
        score_col = "quality_score" if "quality_score" in df_work.columns else "sharpe"

        # --- Step 1: PnL correlation ---
        pnl_success = False
        try:
            pnl_corr = self.calculate_alpha_corr(df_work["id"].tolist())
            if pnl_corr is not None and not pnl_corr.empty:
                df_work = self._filter_by_pnl_corr(df_work, pnl_corr, score_col)
                pnl_success = True
        except Exception as e:
            self.logger.error(f"Layer 3 [Correlation]: PnL correlation 计算失败: {e}")

        if not pnl_success:
            self.logger.warning("Layer 3 [Correlation]: 回退到 prodCorrelation")
            df_work = self._filter_by_prod_corr_fallback(df_work)

        # Rollback check after PnL corr
        if len(df_work) < self.config["min_alpha_count"]:
            self.logger.warning(
                f"Layer 3 [Correlation]: 过滤后 {len(df_work)} 个 < {self.config['min_alpha_count']}，回退"
            )
            original_df["high_corr_flag"] = False
            return original_df

        # --- Step 2: Drawdown overlap (threshold 0.7) ---
        if len(df_work) > self.config["min_alpha_count"]:
            try:
                returns = self.get_alpha_results(df_work["id"].tolist())
                if not returns.empty:
                    dd_mask = self._compute_drawdown_mask(returns)
                    to_remove_dd = self._find_drawdown_overlap_pairs(
                        dd_mask,
                        df_work,
                        score_col,
                        threshold=self.config["drawdown_overlap_threshold"],
                        pnl_corr=pnl_corr if pnl_success else None,
                        min_pnl_corr=self.config["drawdown_overlap_min_pnl_corr"],
                    )
                    if to_remove_dd:
                        removed_dd_df = df_work[df_work["id"].isin(to_remove_dd)]
                        if "type" in removed_dd_df.columns and not removed_dd_df.empty:
                            n_removed_dd_super = (removed_dd_df["type"] == "SUPER").sum()
                            n_removed_dd_regular = len(removed_dd_df) - n_removed_dd_super
                        else:
                            n_removed_dd_super = 0
                            n_removed_dd_regular = len(removed_dd_df)
                        df_work = df_work[~df_work["id"].isin(to_remove_dd)].copy()
                        self.logger.info(
                            f"Layer 3 [Correlation] [DD overlap]: 淘汰 {len(to_remove_dd)} 个 "
                            f"(REGULAR={n_removed_dd_regular}, SUPER={n_removed_dd_super})"
                        )
            except Exception as e:
                self.logger.error(f"Layer 3 [Correlation]: drawdown overlap 检测失败: {e}")

        # Final rollback
        if len(df_work) < self.config["min_alpha_count"]:
            self.logger.warning(
                f"Layer 3 [Correlation]: 最终过滤后 {len(df_work)} 个 < {self.config['min_alpha_count']}，回退到过滤前"
            )
            original_df["high_corr_flag"] = False
            return original_df

        return df_work

    def apply_diversification_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Layer 4 [Diversification]: 策略分散（V3 增强）
        - dataset_tags: 多标签 diversification，每个 tag 类别保留 top_k
        - neutralization: 风险暴露方式限额
        - SuperAlpha 直接保留
        """
        if df.empty:
            return df

        # 分离 SuperAlpha 和 REGULAR
        mask_super = df["type"] == "SUPER"
        df_super = df[mask_super].copy() if mask_super.any() else pd.DataFrame()
        df_regular = df[~mask_super].copy() if (~mask_super).any() else pd.DataFrame()

        if df_regular.empty:
            self.logger.info(f"Layer 4 [Diversification]: 无 REGULAR Alpha，保留 {len(df_super)} 个 SuperAlpha")
            return df_super

        cfg = self.config
        n = len(df_regular)
        top_k_neutralization = max(
            cfg["div_neutralization_min"],
            min(cfg["div_neutralization_max"], n // cfg["div_neutralization_divisor"]),
        )
        top_k_dataset_tag = max(
            cfg["div_dataset_tag_min"],
            min(cfg["div_dataset_tag_max"], n // cfg["div_dataset_tag_divisor"]),
        )

        self.logger.info(
            f"Layer 4 [Diversification]: REGULAR={n}个, neutralization限额={top_k_neutralization}, "
            f"dataset_tag限额={top_k_dataset_tag}, SuperAlpha={len(df_super)}个直接保留"
        )

        # 按 quality_score 排序（V3 用 quality_score 替代 sharpe）
        sort_col = "quality_score" if "quality_score" in df_regular.columns else "sharpe"
        df_regular = df_regular.sort_values(sort_col, ascending=False)

        # 依次应用各维度限额（仅当该维度有足够多样性时才限额）
        df_regular_filtered = df_regular.copy()

        def _log_filter_step(df_before, df_after, dim, top_k):
            """打印每一步过滤的详细日志"""
            kept = len(df_after)
            removed = len(df_before) - kept
            self.logger.info(
                f"Layer 4 [Diversification] [{dim}]: {len(df_before)} -> {kept} 个"
                f"(淘汰 {removed} 个, 限额={top_k})"
            )
            # 打印每个分组的保留情况
            counts_before = df_before[dim].value_counts().sort_index()
            counts_after = df_after[dim].value_counts().sort_index()
            for group in counts_before.index:
                before_n = counts_before[group]
                after_n = counts_after.get(group, 0)
                removed_n = before_n - after_n
                status = "✅全保留" if removed_n == 0 else f"淘汰{removed_n}个"
                self.logger.info(
                    f"  [{dim}] {group}: {before_n} -> {after_n} ({status})"
                )
            return df_after

        # dataset_tags: 多标签 diversification——每个 tag 类别保留 top_k，Alpha 只要在任意一个 tag 中达标即可保留
        if "dataset_tags" in df_regular_filtered.columns:
            # 展开多标签
            tag_rows = []
            for _, row in df_regular_filtered.iterrows():
                tags = row.get("dataset_tags", ["unknown"])
                if not isinstance(tags, list):
                    tags = [str(tags)]
                for tag in tags:
                    tag_rows.append({
                        "id": row["id"],
                        "tag": tag,
                        sort_col: row[sort_col],
                    })
            tag_df = pd.DataFrame(tag_rows)
            unique_tags = tag_df["tag"].nunique()

            if unique_tags > 1:
                df_before = df_regular_filtered.copy()

                # 对每个 tag 取 top_k，收集所有保留的 Alpha ID（并集）
                kept_ids = set()
                tag_stats = {}
                for tag, group in tag_df.groupby("tag"):
                    before_n = len(group)
                    top_ids = group.nlargest(top_k_dataset_tag, sort_col)["id"].tolist()
                    kept_ids.update(top_ids)
                    tag_stats[tag] = {"before": before_n, "after": len(top_ids), "ids": top_ids}

                df_regular_filtered = df_regular_filtered[df_regular_filtered["id"].isin(kept_ids)].sort_values(sort_col, ascending=False)
                removed = len(df_before) - len(df_regular_filtered)
                self.logger.info(
                    f"Layer 4 [Diversification] [dataset_tags]: {len(df_before)} -> {len(df_regular_filtered)} 个"
                    f"(淘汰 {removed} 个, 每个tag限额={top_k_dataset_tag}, unique_tags={unique_tags})"
                )
                for tag, stats in sorted(tag_stats.items()):
                    status = "✅全保留" if stats["before"] <= stats["after"] else f"淘汰{stats['before'] - stats['after']}个"
                    self.logger.info(
                        f"  [dataset_tags] {tag}: {stats['before']} -> {stats['after']} ({status})"
                    )
            else:
                self.logger.info(
                    f"Layer 4 [Diversification] [dataset_tags]: 跳过 (unique_tags={unique_tags} <= 1)"
                )
        else:
            self.logger.info("Layer 4 [Diversification] [dataset_tags]: 列不存在，跳过")

        if df_regular_filtered["neutralization"].nunique() > top_k_neutralization:
            df_before = df_regular_filtered.copy()
            df_regular_filtered = df_regular_filtered.groupby("neutralization", group_keys=False).head(top_k_neutralization)
            df_regular_filtered = df_regular_filtered.sort_values(sort_col, ascending=False)
            df_regular_filtered = _log_filter_step(df_before, df_regular_filtered, "neutralization", top_k_neutralization)
        else:
            self.logger.info(
                f"Layer 4 [Diversification] [neutralization]: 跳过 (nunique={df_regular_filtered['neutralization'].nunique()} <= 限额={top_k_neutralization})"
            )



        # 检查是否不足门槛
        total_after = len(df_regular_filtered) + len(df_super)
        if total_after < self.config["min_alpha_count"]:
            self.logger.warning(
                f"Layer 4 [Diversification]: 过滤后仅 {total_after} 个(REGULAR {len(df_regular_filtered)} + SuperAlpha {len(df_super)})，"
                f"不足门槛 {self.config['min_alpha_count']}，跳过 diversification"
            )
            df_regular_filtered = df_regular

        # 合并
        df_result = pd.concat([df_regular_filtered, df_super], ignore_index=True)
        self.logger.info(
            f"Layer 4 [Diversification]: 最终 {len(df_result)} 个 Alpha "
            f"(REGULAR {len(df_regular_filtered)} + SuperAlpha {len(df_super)})"
        )
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
        fetch_yearly_stats: bool = True,
    ) -> pd.DataFrame:
        """
        执行完整的 V3 粗筛 pipeline

        Args:
            region: 目标 region
            start_date: 创建日期下限
            delay: 可选 delay（默认 None，由 API 返回所有 delay）
            use_cache: 是否使用候选列表缓存
            fetch_yearly_stats: 是否获取 yearly-stats（首次建议 True，后续可 False 读缓存）

        Returns:
            带完整评分的 DataFrame
        """
        # 1. 获取候选
        regular_df = self.fetch_candidates(region, start_date, delay, type_filter="REGULAR", use_cache=use_cache)
        super_df = self.fetch_candidates(region, start_date, delay, type_filter="SUPER", use_cache=use_cache)
        # 避免 FutureWarning：过滤空 DataFrame
        dfs_to_concat = [d for d in [regular_df, super_df] if not d.empty]
        if not dfs_to_concat:
            return pd.DataFrame()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            df = pd.concat(dfs_to_concat, ignore_index=True)

        if df.empty:
            return df

        n_super = (df["type"] == "SUPER").sum()
        n_regular = len(df) - n_super
        self.logger.info(f"fetch_candidates 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        # 2. Layer 1 [HardFilter]: Quality Gate
        df = self.apply_hard_filters(df)
        n_super = (df["type"] == "SUPER").sum()
        n_regular = len(df) - n_super
        self.logger.info(f"Layer 1 [HardFilter] 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        if len(df) < self.config["min_alpha_count"]:
            self.logger.warning("标准门槛不足，放宽重试")
            regular_df = self.fetch_candidates(region, start_date, delay, type_filter="REGULAR", use_cache=use_cache)
            super_df = self.fetch_candidates(region, start_date, delay, type_filter="SUPER", use_cache=use_cache)
            df = pd.concat([regular_df, super_df], ignore_index=True)
            df = self.apply_hard_filters(df, relaxed=True)
            n_super = (df["type"] == "SUPER").sum()
            n_regular = len(df) - n_super
            self.logger.info(f"Layer 1 [HardFilter] (relaxed) 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        if len(df) < self.config["min_alpha_count"]:
            self.logger.error(f"粗筛后仅 {len(df)} 个，不足门槛，终止")
            return df

        # 3. 获取 yearly-stats（V3 新增）
        if fetch_yearly_stats:
            alpha_ids = df["id"].tolist()
            yearly_stats_map = self.fetch_yearly_stats_batch(alpha_ids)
            df["yearly_stats"] = df["id"].map(lambda aid: yearly_stats_map.get(aid, []))
        else:
            df["yearly_stats"] = [[] for _ in range(len(df))]

        # 3.5 计算 PnL correlation 矩阵（供 uniqueness_score 和 Layer 3 [Correlation] 使用）
        if not df.empty:
            try:
                pnl_corr = self.calculate_alpha_corr(df["id"].tolist())
                if pnl_corr is not None and not pnl_corr.empty:
                    mean_corr = pnl_corr.mean(axis=1)
                    df["pnl_corr_mean"] = df["id"].map(mean_corr.to_dict())
                    self.logger.info(f"PnL correlation 矩阵: {pnl_corr.shape}")
            except Exception as e:
                self.logger.error(f"PnL correlation 矩阵计算失败: {e}")
                df["pnl_corr_mean"] = None

        # 4. 计算所有评分（V3 新增）
        df = self._compute_all_scores(df)

        # 5. Layer 2 [Investability]: 可投资性软检查（V3 新增，标记不降权排除）
        df = self.apply_investability_filter(df)
        n_super = (df["type"] == "SUPER").sum()
        n_regular = len(df) - n_super
        self.logger.info(f"Layer 2 [Investability] 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        # 6. Layer 3 [Correlation]: PnL correlation + drawdown overlap 过滤
        df = self.apply_correlation_filter(df)
        n_super = (df["type"] == "SUPER").sum()
        n_regular = len(df) - n_super
        self.logger.info(f"Layer 3 [Correlation] 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        # 7. Layer 4 [Diversification]: 策略分散
        df = self.apply_diversification_filter(df)
        n_super = (df["type"] == "SUPER").sum()
        n_regular = len(df) - n_super
        self.logger.info(f"Layer 4 [Diversification] 后: REGULAR={n_regular}, SUPER={n_super}, 总计={len(df)}")

        self.logger.info(f"{'='*50} V3 粗筛完成: {len(df)} 个 Alpha {'='*50}")
        return df

    # ==================================================================
    # 额外工具（继承 V2）
    # ==================================================================
    def get_low_correlation_subset(
        self,
        df: pd.DataFrame,
        threshold: float = None,
        max_size: int = None,
        sort_by: str = "quality_score",
    ) -> pd.DataFrame:
        """基于 PnL 的 greedy max-clique 进一步精简（V3 默认按 quality_score 排序）"""
        cfg = self.config
        threshold = threshold if threshold is not None else cfg["low_correlation_subset_threshold"]
        max_size = max_size if max_size is not None else cfg["low_correlation_subset_max_size"]

        if len(df) <= max_size:
            return df

        # 使用 quality_score 替代 sharpe 作为排序依据
        if sort_by not in df.columns:
            sort_by = "sharpe"

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
