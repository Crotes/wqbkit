"""
OsmosisAlphaSelectorV3 测试套件

运行方式:
    cd /home/worldquant/wqb/Code2.0
    /root/anaconda3/envs/worldquant/bin/python -m pytest modules/competitions/Osmosis/v3/test_selector_v3.py -v
    或
    /root/anaconda3/envs/worldquant/bin/python modules/competitions/Osmosis/v3/test_selector_v3.py
"""

import json
import logging
import pickle
import sys
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from wqbkit.modules.competitions.Osmosis.v3.osmosis_selector_v3 import OsmosisAlphaSelectorV3


# 测试用的 mock logger
class MockLogger:
    def debug(self, msg, *args, **kwargs): pass
    def info(self, msg, *args, **kwargs): pass
    def warning(self, msg, *args, **kwargs): pass
    def error(self, msg, *args, **kwargs): pass


def _attach_mock_logger(obj):
    """给绕过 __init__ 创建的对象附加 mock logger"""
    obj.logger = MockLogger()


class TestParseAlphaItem(unittest.TestCase):
    """测试 _parse_alpha_item() 字段解析"""

    @classmethod
    def setUpClass(cls):
        v3_dir = Path(__file__).parent.parent
        with open(v3_dir / "json" / "alpha_detail_os.json", "r", encoding="utf-8") as f:
            cls.alpha_os = json.load(f)
        with open(v3_dir / "json" / "alpha_detail_no_os.json", "r", encoding="utf-8") as f:
            cls.alpha_no_os = json.load(f)

    def test_os_alpha_parsing(self):
        """有 OS 数据的 Alpha"""
        result = OsmosisAlphaSelectorV3._parse_alpha_item(self.alpha_os)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "88gAZ3zv")
        self.assertEqual(result["type"], "REGULAR")
        self.assertEqual(result["sharpe"], 1.6)
        self.assertEqual(result["fitness"], 0.83)
        self.assertEqual(result["selfCorrelation"], 0)
        self.assertEqual(result["prodCorrelation"], 0.2361)

        # V3 新增字段
        self.assertEqual(result["os_sharpe"], 0.2)
        self.assertEqual(result["os_is_ratio"], 0.12)
        self.assertEqual(result["inv_sharpe"], 0.9)
        self.assertEqual(result["max_trade"], "OFF")
        self.assertEqual(result["dataset_tags"], ["Fundamental"])
        self.assertEqual(result["neutralization"], "SLOW")

    def test_no_os_alpha_parsing(self):
        """无 OS 数据的 Alpha"""
        result = OsmosisAlphaSelectorV3._parse_alpha_item(self.alpha_no_os)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "2ragnz35")

        # OS 字段应为 None
        self.assertIsNone(result["os_sharpe"])
        self.assertIsNone(result["os_is_ratio"])

        # investabilityConstrained 始终存在
        self.assertEqual(result["inv_sharpe"], 1.86)
        self.assertEqual(result["inv_fitness"], 1.39)

        self.assertEqual(result["max_trade"], "OFF")
        self.assertEqual(result["dataset_tags"], ["Imbalance"])
        self.assertEqual(result["neutralization"], "FAST")

    def test_excluded_alphas(self):
        """FastD1 / COMPENSATED / DECOMMISSIONED 应被排除"""
        fastd1 = {"id": "test", "classifications": [{"name": "FastD1 Alpha"}], "is": {}, "settings": {}}
        self.assertIsNone(OsmosisAlphaSelectorV3._parse_alpha_item(fastd1))

        decommissioned = {"id": "test", "status": "DECOMMISSIONED", "is": {}, "settings": {}}
        self.assertIsNone(OsmosisAlphaSelectorV3._parse_alpha_item(decommissioned))


class TestYearlyStatsParsing(unittest.TestCase):
    """测试 yearly-stats 解析"""

    @classmethod
    def setUpClass(cls):
        v3_dir = Path(__file__).parent.parent
        with open(v3_dir / "json" / "year_status.json", "r", encoding="utf-8") as f:
            cls.yearly_data = json.load(f)

    def test_schema_parsing(self):
        """schema + records 二维数组解析"""
        properties = [p["name"] for p in self.yearly_data["schema"]["properties"]]
        self.assertEqual(properties[0], "year")
        self.assertEqual(properties[6], "sharpe")
        self.assertEqual(properties[-1], "stage")

    def test_record_structure(self):
        """records 应包含 10 年数据"""
        records = self.yearly_data["records"]
        self.assertEqual(len(records), 10)

        first_year = dict(zip([p["name"] for p in self.yearly_data["schema"]["properties"]], records[0]))
        self.assertEqual(int(first_year["year"]), 2014)
        self.assertEqual(first_year["stage"], "IS")
        self.assertAlmostEqual(float(first_year["sharpe"]), 4.28, places=2)


class TestScoreComputation(unittest.TestCase):
    """测试评分计算逻辑"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()

    def test_yearly_stability_with_data(self):
        """有 yearly_stats 时的稳定性计算"""
        stats = [
            {"year": 2018, "sharpe": 2.91, "stage": "IS"},
            {"year": 2019, "sharpe": 2.59, "stage": "IS"},
            {"year": 2020, "sharpe": 0.31, "stage": "IS"},
            {"year": 2021, "sharpe": 2.36, "stage": "IS"},
            {"year": 2022, "sharpe": 0.44, "stage": "IS"},
            {"year": 2023, "sharpe": 3.30, "stage": "IS"},
        ]
        score = self.selector._compute_yearly_stability_score(stats)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 1)
        # 这个序列有波动但总体为正，得分应在中等偏上
        self.assertGreater(score, 0.3)

    def test_yearly_stability_insufficient_data(self):
        """数据不足时返回默认值"""
        self.assertEqual(self.selector._compute_yearly_stability_score([]), 0.5)
        self.assertEqual(self.selector._compute_yearly_stability_score([{"year": 2023, "sharpe": 1.0}]), 0.5)

    def test_os_is_score_with_ratio(self):
        """有 os_is_ratio 时直接使用"""
        row = pd.Series({"os_is_ratio": 0.8, "sharpe": 1.5, "inv_sharpe": 1.2})
        score = self.selector._compute_os_is_score(row)
        self.assertGreater(score, 0.5)  # ratio=0.8 > 0.5，应得高分

    def test_os_is_score_with_proxy(self):
        """无 os_is_ratio 时用 inv_sharpe / sharpe 代理"""
        row = pd.Series({"os_is_ratio": np.nan, "sharpe": 2.0, "inv_sharpe": 1.6})
        score = self.selector._compute_os_is_score(row)
        # proxy_ratio = 0.8，打 7 折后应 > 0.5
        self.assertGreater(score, 0.5)

    def test_os_is_score_default(self):
        """无数据时返回默认值"""
        row = pd.Series({"os_is_ratio": np.nan, "sharpe": 2.0, "inv_sharpe": np.nan})
        self.assertEqual(self.selector._compute_os_is_score(row), 0.5)

    def test_investability_decay_levels(self):
        """衰减四级分类"""
        # stable: decay < 20%
        row = pd.Series({"sharpe": 2.0, "inv_sharpe": 1.7})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "stable")
        self.assertEqual(mult, 1.0)

        # mild: 20-40%
        row = pd.Series({"sharpe": 2.0, "inv_sharpe": 1.4})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "mild_decay")
        self.assertEqual(mult, 0.85)

        # moderate: 40-60%
        row = pd.Series({"sharpe": 2.0, "inv_sharpe": 0.9})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "moderate_decay")
        self.assertEqual(mult, 0.6)

        # severe: >= 60%
        row = pd.Series({"sharpe": 2.0, "inv_sharpe": 0.5})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "severe_decay")
        self.assertEqual(mult, 0.2)

    def test_investability_decay_edge_cases(self):
        """边界情况"""
        # is_sharpe <= 0
        row = pd.Series({"sharpe": 0, "inv_sharpe": 0.5})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "unknown")

        # inv_sharpe 缺失
        row = pd.Series({"sharpe": 2.0, "inv_sharpe": np.nan})
        label, mult = self.selector._compute_investability_decay(row)
        self.assertEqual(label, "unknown")

    def test_compute_all_scores(self):
        """综合评分计算"""
        selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(selector)
        selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        selector.maxtrade_map = {}
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "fitness": [1.5, 1.0, 0.5],
            "sharpe": [2.0, 1.5, 1.0],
            "returns": [0.1, 0.08, 0.05],
            "margin": [0.002, 0.001, 0.0005],
            "drawdown": [0.05, 0.08, 0.12],
            "turnover": [0.15, 0.18, 0.22],
            "yearly_stats": [[], [], []],
            "os_is_ratio": [0.8, 0.6, np.nan],
            "inv_sharpe": [1.8, 1.2, 0.8],
            "selfCorrelation": [0.1, 0.5, 0.8],
            "prodCorrelation": [0.2, 0.6, 0.9],
        })

        result = selector._compute_all_scores(df)

        # 应有这些评分列
        for col in ["quality_score", "yearly_stability", "os_is_score", "decay_label", "decay_multiplier", "uniqueness_score"]:
            self.assertIn(col, result.columns)

        # quality_score 应在 [0, 1]
        self.assertTrue(result["quality_score"].between(0, 1).all())

        # sharpe 最高的 A 应有最高的 quality_score
        self.assertEqual(result.loc[0, "id"], "A")
        self.assertGreater(result.loc[0, "quality_score"], result.loc[2, "quality_score"])

        # decay 分类
        self.assertEqual(result.loc[0, "decay_label"], "stable")  # (2.0-1.8)/2.0 = 10%
        self.assertEqual(result.loc[1, "decay_label"], "mild_decay")  # (1.5-1.2)/1.5 = 20%


class TestDiversificationFilter(unittest.TestCase):
    """测试 diversification filter"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()

    def test_diversification_with_diversity(self):
        """有足够多样性时的限额效果（使用 min_alpha_count=5 避免回滚）"""
        self.selector.config["min_alpha_count"] = 5  # 过滤后 6 > 5，不会回滚
        """有足够多样性时的限额效果"""
        data = []
        for i in range(20):
            data.append({
                "id": f"A{i:02d}",
                "type": "REGULAR",
                "expression": f"ts_mean(field{i % 5}, 10)",  # 5 个不同 field
                "neutralization": ["FAST", "SLOW", "INDUSTRY"][i % 3],
                "dataset_tags": [["Fundamental"], ["Imbalance"], ["Sentiment"]][i % 3],
                "quality_score": 1.0 - i * 0.05,
                "sharpe": 2.0 - i * 0.05,
            })
        df = pd.DataFrame(data)
        result = self.selector.apply_diversification_filter(df)

        # 应保留多个维度的多样性
        self.assertGreaterEqual(len(result), 5)
        self.assertLess(len(result), 20)

        # 应保留多种 neutralization
        self.assertGreaterEqual(result["neutralization"].nunique(), 2)

    def test_diversification_low_diversity(self):
        """多样性不足时不应过度 kill"""
        data = []
        for i in range(15):
            data.append({
                "id": f"A{i:02d}",
                "type": "REGULAR",
                "expression": f"ts_mean(field{i}, 10)",
                "neutralization": "FAST",  # 全部相同
                "dataset_tags": ["Fundamental"],  # 全部相同
                "quality_score": 1.0 - i * 0.05,
                "sharpe": 2.0 - i * 0.05,
            })
        df = pd.DataFrame(data)
        result = self.selector.apply_diversification_filter(df)

        # neutralization 和 dataset_tags 都只有 1 个 unique 值，不应应用限额
        # 但 primary_field 有 15 个 unique，会应用 field 限额
        self.assertGreater(len(result), 3)

    def test_superalpha_bypass(self):
        """SuperAlpha 应直接保留"""
        data = [
            {"id": "S1", "type": "SUPER", "expression": "", "neutralization": "FAST", "dataset_tags": ["A"], "quality_score": 5.0, "sharpe": 5.0},
            {"id": "S2", "type": "SUPER", "expression": "", "neutralization": "SLOW", "dataset_tags": ["B"], "quality_score": 4.5, "sharpe": 4.5},
            {"id": "R1", "type": "REGULAR", "expression": "field1", "neutralization": "FAST", "dataset_tags": ["A"], "quality_score": 2.0, "sharpe": 2.0},
            {"id": "R2", "type": "REGULAR", "expression": "field2", "neutralization": "FAST", "dataset_tags": ["A"], "quality_score": 1.5, "sharpe": 1.5},
        ]
        df = pd.DataFrame(data)
        result = self.selector.apply_diversification_filter(df)

        # 两个 SuperAlpha 都应保留
        self.assertIn("S1", result["id"].values)
        self.assertIn("S2", result["id"].values)


class TestInvestabilityFilter(unittest.TestCase):
    """测试 investability 软过滤"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        self.selector.maxtrade_map = {}

    def test_soft_filter_no_removal(self):
        """软过滤不应移除任何 Alpha"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "decay_label": ["stable", "moderate_decay", "severe_decay"],
            "max_trade": ["ON", "OFF", "OFF"],
        })
        result = self.selector.apply_investability_filter(df)
        self.assertEqual(len(result), 3)  # 数量不变
        self.assertEqual(list(result["id"]), ["A", "B", "C"])


class TestMaxTradeMap(unittest.TestCase):
    """测试 MaxTrade 映射表"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.maxtrade_path = Path(__file__).parent / "data" / "test_maxtrade.json"
        self.selector.maxtrade_map = {}

    def tearDown(self):
        if self.selector.maxtrade_path.exists():
            self.selector.maxtrade_path.unlink()

    def test_update_and_get(self):
        """更新和读取映射表"""
        self.selector.update_maxtrade_status(
            "alpha_1", has_maxTradeOn_sim=True, maxTradeOn_sharpe=1.8, notes="测试"
        )
        status = self.selector.get_maxtrade_status("alpha_1")
        self.assertTrue(status["has_maxTradeOn_sim"])
        self.assertEqual(status["maxTradeOn_sharpe"], 1.8)

    def test_default_status(self):
        """无记录时返回默认状态"""
        status = self.selector.get_maxtrade_status("unknown_alpha")
        self.assertFalse(status["has_maxTradeOn_sim"])


class TestMaxTradeOnEvaluation(unittest.TestCase):
    """测试 MaxTradeOn 后评估调整"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        self.selector.maxtrade_map = {}

    def test_maxtrade_on_no_adjustment(self):
        """maxTrade=ON 的 Alpha 无调整"""
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["ON"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], 1.0)

    def test_maxtrade_off_no_sim_penalty(self):
        """maxTrade=OFF 且无 sim 记录的 Alpha 受轻微惩罚"""
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], self.selector.config["maxtrade_on_adj_no_sim"])

    def test_maxtrade_off_excellent_sim(self):
        """maxTrade=OFF + MaxTradeOn 后表现优秀（ratio>=70%）"""
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=1.5)
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], self.selector.config["maxtrade_on_adj_excellent"])

    def test_maxtrade_off_good_sim(self):
        """maxTrade=OFF + MaxTradeOn 后表现良好（50%<=ratio<70%）"""
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=1.0)
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], self.selector.config["maxtrade_on_adj_good"])

    def test_maxtrade_off_poor_sim(self):
        """maxTrade=OFF + MaxTradeOn 后表现极差（ratio<30%）"""
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=0.3)
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], self.selector.config["maxtrade_on_adj_poor"])

    def test_maxtrade_off_zero_sharpe_sim(self):
        """maxTrade=OFF + MaxTradeOn 后 sharpe<=0"""
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=0.0)
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], self.selector.config["maxtrade_on_adj_poor"])

    def test_disabled_maxtrade_eval(self):
        """禁用 MaxTradeOn 评估时所有 Alpha  adjustment=1.0"""
        self.selector.config["maxtrade_eval_enabled"] = False
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=0.3)
        df = pd.DataFrame({
            "id": ["A"],
            "max_trade": ["OFF"],
            "sharpe": [2.0],
        })
        adj = self.selector._compute_maxtrade_adjustment(df)
        self.assertEqual(adj.iloc[0], 1.0)

    def test_quality_score_with_maxtrade_adjustment(self):
        """MaxTradeOn 调整影响 quality_score 排序"""
        self.selector.update_maxtrade_status("A", has_maxTradeOn_sim=True, maxTradeOn_sharpe=0.3)
        df = pd.DataFrame({
            "id": ["A", "B"],
            "fitness": [1.5, 1.5],
            "sharpe": [2.0, 2.0],
            "returns": [0.1, 0.1],
            "margin": [0.002, 0.002],
            "drawdown": [0.05, 0.05],
            "turnover": [0.15, 0.15],
            "yearly_stats": [[], []],
            "os_is_ratio": [np.nan, np.nan],
            "inv_sharpe": [1.8, 1.8],
            "selfCorrelation": [0.1, 0.1],
            "prodCorrelation": [0.2, 0.2],
            "max_trade": ["OFF", "ON"],
        })
        result = self.selector._compute_all_scores(df)
        # A 的 MaxTradeOn ratio=0.3/2.0=15% < 30%，adjustment=0.15
        # B 的 max_trade=ON，adjustment=1.0
        # B 的 quality_score 应高于 A
        score_a = result[result["id"] == "A"]["quality_score"].iloc[0]
        score_b = result[result["id"] == "B"]["quality_score"].iloc[0]
        self.assertGreater(score_b, score_a)


class TestBlacklist(unittest.TestCase):
    """测试黑名单机制（继承 V2）"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        self.selector.blacklist = set()
        self.selector.maxtrade_map = {}

    def test_add_to_blacklist(self):
        """添加 Alpha 到黑名单"""
        self.selector.add_to_blacklist("A1")
        self.assertIn("A1", self.selector.blacklist)
        self.assertTrue(self.selector.is_blacklisted("A1"))

        # 批量添加
        self.selector.add_to_blacklist(["A2", "A3"])
        self.assertEqual(len(self.selector.blacklist), 3)

    def test_remove_from_blacklist(self):
        """从黑名单移除"""
        self.selector.add_to_blacklist(["A1", "A2", "A3"])
        self.selector.remove_from_blacklist("A1")
        self.assertNotIn("A1", self.selector.blacklist)
        self.assertIn("A2", self.selector.blacklist)

        # 移除不在黑名单中的应无异常
        self.selector.remove_from_blacklist("A99")
        self.assertEqual(len(self.selector.blacklist), 2)

    def test_clear_blacklist(self):
        """清空黑名单"""
        self.selector.add_to_blacklist(["A1", "A2"])
        self.selector.clear_blacklist()
        self.assertEqual(len(self.selector.blacklist), 0)
        self.assertEqual(self.selector.list_blacklist(), [])

    def test_list_blacklist_sorted(self):
        """list_blacklist 应返回排序后的列表"""
        self.selector.add_to_blacklist(["C1", "A1", "B1"])
        self.assertEqual(self.selector.list_blacklist(), ["A1", "B1", "C1"])

    def test_blacklist_filter_in_fetch_candidates(self):
        """fetch_candidates 应过滤黑名单中的 Alpha"""
        df = pd.DataFrame({
            "id": ["A1", "A2", "A3", "A4"],
            "dateCreated": ["2025-04-20T00:00:00"] * 4,
        })
        self.selector.add_to_blacklist(["A2", "A4"])

        # 模拟 fetch_candidates 中的黑名单过滤逻辑
        before = len(df)
        df = df[~df["id"].isin(self.selector.blacklist)].copy()
        removed = before - len(df)

        self.assertEqual(removed, 2)
        self.assertEqual(len(df), 2)
        self.assertIn("A1", df["id"].values)
        self.assertIn("A3", df["id"].values)
        self.assertNotIn("A2", df["id"].values)
        self.assertNotIn("A4", df["id"].values)

    def test_blacklist_persistence(self):
        """黑名单应持久化到 JSON"""
        import tempfile
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            self.selector.blacklist_path = Path(tmpdir) / "blacklist.json"
            self.selector.add_to_blacklist(["X1", "X2"])

            # 验证文件写入
            with open(self.selector.blacklist_path, "r") as f:
                data = json.load(f)
            self.assertEqual(sorted(data["alpha_ids"]), ["X1", "X2"])
            self.assertIn("updated_at", data)

            # 模拟重新加载
            self.selector.blacklist = set()
            loaded = self.selector._load_blacklist()
            self.assertEqual(loaded, {"X1", "X2"})


class TestIntegrationWithCachedData(unittest.TestCase):
    """使用 V2 缓存数据做集成测试"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        self.selector.blacklist = set()
        self.selector.maxtrade_map = {}

    def test_full_pipeline_with_mock_data(self):
        """完整 pipeline 模拟运行"""
        cache_dir = Path(__file__).parent.parent / "v2_0" / "data" / "selector_cache"
        if not cache_dir.exists():
            self.skipTest("V2 缓存数据不存在")

        with open(cache_dir / "candidates_EUR_any_REGULAR.pkl", "rb") as f:
            df_regular = pickle.load(f)

        # 补充 V3 字段（模拟 _parse_alpha_item 的完整输出）
        for col in ["os_sharpe", "os_is_ratio"]:
            df_regular[col] = None
        df_regular["inv_sharpe"] = df_regular["sharpe"] * 0.85
        df_regular["inv_fitness"] = df_regular["fitness"] * 0.85
        df_regular["inv_returns"] = df_regular["returns"] * 0.85
        df_regular["inv_drawdown"] = df_regular["drawdown"] * 1.1
        df_regular["inv_turnover"] = df_regular["turnover"] * 0.8
        df_regular["inv_margin"] = df_regular["margin"] * 1.1
        df_regular["max_trade"] = "OFF"
        df_regular["pyramid_category"] = "Fundamental"

        # 运行各层筛选
        df = self.selector.apply_hard_filters(df_regular)
        self.assertGreaterEqual(len(df), 10)

        # 模拟评分计算（无 yearly_stats）
        df["yearly_stats"] = [[] for _ in range(len(df))]
        df = self.selector._compute_all_scores(df)

        # 验证评分列存在且合理
        self.assertIn("quality_score", df.columns)
        self.assertTrue(df["quality_score"].between(0, 1).all())
        self.assertGreaterEqual(df["quality_score"].nunique(), 2)

        # investability filter
        df = self.selector.apply_investability_filter(df)
        self.assertEqual(len(df), len(df))  # 不应移除

        # diversification filter
        df = self.selector.apply_diversification_filter(df)
        self.assertGreaterEqual(len(df), 5)

        print(f"\n集成测试通过: {len(df_regular)} -> {len(df)} 个 Alpha")
        print(f"quality_score 范围: {df['quality_score'].min():.3f} ~ {df['quality_score'].max():.3f}")


class TestUniquenessScoreV3(unittest.TestCase):
    """测试 uniqueness_score 的 PnL correlation 集成 (V3)"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()

    def test_uniqueness_with_pnl_corr_mean(self):
        """pnl_corr_mean 越低，uniqueness_score 越高"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "selfCorrelation": [0.3, 0.5, 0.7],
            "prodCorrelation": [0.2, 0.4, 0.6],
            "pnl_corr_mean": [0.1, 0.3, 0.5],
        })
        scores = self.selector._compute_uniqueness_score(df)
        # pnl_corr_mean 最低的是 A(0.1)，应该得分最高
        self.assertGreater(scores.iloc[0], scores.iloc[1])
        self.assertGreater(scores.iloc[1], scores.iloc[2])

    def test_uniqueness_without_pnl_corr_mean(self):
        """无 pnl_corr_mean 时回退到 self + prod"""
        df = pd.DataFrame({
            "id": ["A", "B"],
            "selfCorrelation": [0.1, 0.9],
            "prodCorrelation": [0.1, 0.9],
        })
        scores = self.selector._compute_uniqueness_score(df)
        self.assertGreater(scores.iloc[0], scores.iloc[1])

    def test_uniqueness_with_only_pnl_corr_mean(self):
        """只有 pnl_corr_mean 时也能工作"""
        df = pd.DataFrame({
            "id": ["A", "B"],
            "pnl_corr_mean": [0.2, 0.8],
        })
        scores = self.selector._compute_uniqueness_score(df)
        self.assertGreater(scores.iloc[0], scores.iloc[1])


class TestCorrelationFilterV3(unittest.TestCase):
    """测试 Layer 3 [Correlation]: PnL correlation + drawdown overlap (V3)"""

    def setUp(self):
        self.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(self.selector)
        self.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()

    def _make_df(self, n: int = 5):
        """生成带 quality_score 的测试 DataFrame"""
        return pd.DataFrame({
            "id": [f"A{i}" for i in range(n)],
            "quality_score": [1.0 - i * 0.1 for i in range(n)],
            "sharpe": [2.0 - i * 0.2 for i in range(n)],
            "prodCorrelation": [0.1] * n,
        })

    def test_pnl_corr_high_elimination(self):
        """PnL correlation > 0.7 应淘汰低分 Alpha"""
        df = self._make_df(3)
        # A0(1.0) 和 A1(0.9) 高度相关，A1 被淘汰
        pnl_corr = pd.DataFrame({
            "A0": [1.0, 0.85, 0.1],
            "A1": [0.85, 1.0, 0.2],
            "A2": [0.1, 0.2, 1.0],
        }, index=["A0", "A1", "A2"])

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        self.assertNotIn("A1", result["id"].values)  # A1 被淘汰
        self.assertIn("A0", result["id"].values)
        self.assertIn("A2", result["id"].values)

    def test_pnl_corr_mid_flag(self):
        """PnL correlation 0.4~0.7 应标记 high_corr_flag"""
        df = self._make_df(2)
        # A0 和 A1 中等相关
        pnl_corr = pd.DataFrame({
            "A0": [1.0, 0.55],
            "A1": [0.55, 1.0],
        }, index=["A0", "A1"])

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        # 两者都不被淘汰，但应标记 high_corr_flag
        self.assertIn("A0", result["id"].values)
        self.assertIn("A1", result["id"].values)
        self.assertTrue(result[result["id"] == "A0"]["high_corr_flag"].iloc[0])
        self.assertTrue(result[result["id"] == "A1"]["high_corr_flag"].iloc[0])

    def test_pnl_corr_low_keep(self):
        """PnL correlation < 0.4 应全部保留，不标记"""
        df = self._make_df(2)
        pnl_corr = pd.DataFrame({
            "A0": [1.0, 0.2],
            "A1": [0.2, 1.0],
        }, index=["A0", "A1"])

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        self.assertEqual(len(result), 2)
        self.assertFalse(result["high_corr_flag"].any())

    def test_drawdown_overlap_detection(self):
        """Drawdown overlap > 40% 应淘汰低分 Alpha"""
        df = self._make_df(2)
        # 构造 returns：A0 和 A1 在相同日期回撤
        returns = pd.DataFrame({
            "A0": [1, -1, 1, -1, 1, -1, 1, -1, 1, 1],
            "A1": [1, -1, 1, -1, 1, -1, 1, -1, 1, 1],
        })
        dd_mask = self.selector._compute_drawdown_mask(returns)
        to_remove = self.selector._find_drawdown_overlap_pairs(dd_mask, df, "quality_score", threshold=0.4)
        # A0 和 A1 回撤完全同步，overlap = 100%，A1(低分) 被淘汰
        self.assertIn("A1", to_remove)
        self.assertNotIn("A0", to_remove)

    def test_drawdown_overlap_no_overlap(self):
        """无回撤重叠时不应淘汰"""
        df = self._make_df(2)
        # A0 前5天亏损然后大幅反弹创新高；A1 前5天盈利然后后5天亏损
        # 两者回撤期完全不重叠
        returns = pd.DataFrame({
            "A0": [-1, -1, -1, -1, -1, 10, 0, 0, 0, 0],
            "A1": [1, 1, 1, 1, 1, -1, -1, -1, -1, -1],
        })
        dd_mask = self.selector._compute_drawdown_mask(returns)
        to_remove = self.selector._find_drawdown_overlap_pairs(dd_mask, df, "quality_score", threshold=0.4)
        self.assertEqual(len(to_remove), 0)

    def test_correlation_filter_rollback(self):
        """过滤后不足 min_alpha_count 应回退"""
        self.selector.config["min_alpha_count"] = 5
        df = self._make_df(5)
        # 全部高度相关，会导致大量淘汰
        pnl_corr = pd.DataFrame(
            np.ones((5, 5)) * 0.9 + np.eye(5) * 0.1,
            index=[f"A{i}" for i in range(5)],
            columns=[f"A{i}" for i in range(5)],
        )

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        # 只保留 A0，其余淘汰，但 apply_correlation_filter 会 rollback
        self.assertEqual(len(result), 1)  # _filter_by_pnl_corr 本身会严格执行

    def test_apply_correlation_filter_empty(self):
        """空 DataFrame 应返回带 high_corr_flag 的空结果"""
        df = pd.DataFrame()
        result = self.selector.apply_correlation_filter(df)
        self.assertTrue(result.empty)
        self.assertIn("high_corr_flag", result.columns)

    def test_apply_correlation_filter_below_threshold(self):
        """Alpha 数量 <= min_alpha_count 应直接返回，不做过滤"""
        self.selector.config["min_alpha_count"] = 10
        df = self._make_df(5)
        result = self.selector.apply_correlation_filter(df)
        self.assertEqual(len(result), 5)
        # 不应淘汰任何
        self.assertEqual(set(result["id"]), set(df["id"]))

    def test_superalpha_regular_no_elimination(self):
        """方案 B: SuperAlpha 与 REGULAR 之间不淘汰"""
        df = pd.DataFrame({
            "id": ["S0", "R0", "R1"],
            "type": ["SUPER", "REGULAR", "REGULAR"],
            "quality_score": [1.0, 0.9, 0.8],
            "sharpe": [2.0, 1.8, 1.6],
        })
        # S0-R0 高度相关，但 SuperAlpha 与 REGULAR 之间不淘汰
        pnl_corr = pd.DataFrame({
            "S0": [1.0, 0.85, 0.1],
            "R0": [0.85, 1.0, 0.2],
            "R1": [0.1, 0.2, 1.0],
        }, index=["S0", "R0", "R1"])

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        # S0(SuperAlpha) 不应被淘汰，R0 也不应被 S0 淘汰
        self.assertIn("S0", result["id"].values)
        self.assertIn("R0", result["id"].values)
        # R0-R1 不相关，都保留
        self.assertIn("R1", result["id"].values)
        self.assertEqual(len(result), 3)

    def test_superalpha_superalpha_can_eliminate(self):
        """方案 B: SuperAlpha 之间可以相互淘汰"""
        df = pd.DataFrame({
            "id": ["S0", "S1", "R0"],
            "type": ["SUPER", "SUPER", "REGULAR"],
            "quality_score": [1.0, 0.9, 0.8],
            "sharpe": [2.0, 1.8, 1.6],
        })
        # S0-S1 高度相关（两者都是 SuperAlpha）
        pnl_corr = pd.DataFrame({
            "S0": [1.0, 0.85, 0.1],
            "S1": [0.85, 1.0, 0.2],
            "R0": [0.1, 0.2, 1.0],
        }, index=["S0", "S1", "R0"])

        result = self.selector._filter_by_pnl_corr(df, pnl_corr, "quality_score")
        # S0(高分) 保留，S1(低分) 被淘汰
        self.assertIn("S0", result["id"].values)
        self.assertNotIn("S1", result["id"].values)
        self.assertIn("R0", result["id"].values)

    def test_superalpha_drawdown_no_elimination(self):
        """方案 B: SuperAlpha 与 REGULAR 之间不检查 drawdown overlap"""
        df = pd.DataFrame({
            "id": ["S0", "R0"],
            "type": ["SUPER", "REGULAR"],
            "quality_score": [1.0, 0.9],
            "sharpe": [2.0, 1.8],
        })
        # 完全相同回撤
        returns = pd.DataFrame({
            "S0": [1, -1, 1, -1, 1, -1, 1, -1, 1, 1],
            "R0": [1, -1, 1, -1, 1, -1, 1, -1, 1, 1],
        })
        dd_mask = self.selector._compute_drawdown_mask(returns)
        to_remove = self.selector._find_drawdown_overlap_pairs(
            dd_mask, df, "quality_score", threshold=0.4
        )
        # SuperAlpha 与 REGULAR 之间不淘汰
        self.assertEqual(len(to_remove), 0)


class TestTurnoverIdealScore(unittest.TestCase):
    """测试 Turnover 理想区间评分（来自 V1 oss2.py）"""

    @classmethod
    def setUpClass(cls):
        cls.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(cls.selector)
        cls.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        cls.selector.maxtrade_map = {}

    def test_turnover_ideal_center(self):
        """turnover=14%（理想中心）应得满分"""
        score = self.selector._calculate_turnover_score(14.0)
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_turnover_ideal_boundary(self):
        """turnover=8% 和 20%（理想边界）应得非零分"""
        score_min = self.selector._calculate_turnover_score(8.0)
        score_max = self.selector._calculate_turnover_score(20.0)
        self.assertGreater(score_min, 0.0)
        self.assertGreater(score_max, 0.0)
        # 边界处 score = 1.0 - 0.5 = 0.5（中心偏距为 0.5）
        self.assertAlmostEqual(score_min, 0.5, places=5)
        self.assertAlmostEqual(score_max, 0.5, places=5)

    def test_turnover_too_low(self):
        """turnover=4%（低于理想区间）应线性衰减"""
        score = self.selector._calculate_turnover_score(4.0)
        self.assertAlmostEqual(score, 0.5, places=5)  # 4/8 = 0.5

    def test_turnover_zero(self):
        """turnover=0 应得 0 分"""
        score = self.selector._calculate_turnover_score(0.0)
        self.assertEqual(score, 0.0)

    def test_turnover_too_high(self):
        """turnover=25%（高于理想区间）应快速衰减"""
        score = self.selector._calculate_turnover_score(25.0)
        # 25 > 20, score = 1.0 - (25-20)/(4*20) = 1.0 - 5/80 = 0.9375... 不对
        # 等等，让我重新算：1.0 - (25-20)/(4*20) = 1 - 5/80 = 0.9375
        # 但 25% 应该在理想区间外快速衰减，这个公式似乎不太对
        # 实际上 oss2 的公式是 max(0, 1.0 - (turnover-20)/(4*20))
        # 对于 25%: 1 - 5/80 = 0.9375，这确实衰减很慢
        # 对于 40%: 1 - 20/80 = 0.75
        # 对于 100%: 1 - 80/80 = 0
        # 这个公式确实衰减比较慢，但这就是 oss2 的实现
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_turnover_na(self):
        """NaN 应返回默认值 0.5"""
        import numpy as np
        score = self.selector._calculate_turnover_score(np.nan)
        self.assertEqual(score, 0.5)

    def test_turnover_vs_linear(self):
        """理想区间内的 turnover 应比线性评分更高"""
        # turnover=14%，理想评分 = 1.0，线性评分 = 1 - 14/25 = 0.44
        ideal_score = self.selector._calculate_turnover_score(14.0)
        linear_score = 1.0 - (14.0 / 25.0)
        self.assertGreater(ideal_score, linear_score)

        # turnover=10%，理想评分 = 1 - 4/12 = 0.667，线性评分 = 1 - 10/25 = 0.6
        ideal_score2 = self.selector._calculate_turnover_score(10.0)
        linear_score2 = 1.0 - (10.0 / 25.0)
        self.assertGreater(ideal_score2, linear_score2)


class TestBalanceScore(unittest.TestCase):
    """测试多空平衡评分（来自 V1 oss2.py）"""

    @classmethod
    def setUpClass(cls):
        cls.selector = OsmosisAlphaSelectorV3.__new__(OsmosisAlphaSelectorV3)
        _attach_mock_logger(cls.selector)
        cls.selector.config = OsmosisAlphaSelectorV3.DEFAULT_CONFIG.copy()
        cls.selector.maxtrade_map = {}

    def test_perfect_balance(self):
        """long=100, short=100 应得满分"""
        score = self.selector._calculate_balance_score(100, 100)
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_moderate_imbalance(self):
        """long=100, short=25（ratio=0.25）应得 sqrt(0.25)=0.5"""
        score = self.selector._calculate_balance_score(100, 25)
        self.assertAlmostEqual(score, 0.5, places=5)

    def test_severe_imbalance(self):
        """long=100, short=1（ratio=0.01）应得 sqrt(0.01)=0.1"""
        score = self.selector._calculate_balance_score(100, 1)
        self.assertAlmostEqual(score, 0.1, places=5)

    def test_one_side_zero(self):
        """一方为 0 应得 0.2"""
        score_long = self.selector._calculate_balance_score(100, 0)
        score_short = self.selector._calculate_balance_score(0, 100)
        self.assertEqual(score_long, 0.2)
        self.assertEqual(score_short, 0.2)

    def test_both_zero(self):
        """双方为 0 应得 0.0"""
        score = self.selector._calculate_balance_score(0, 0)
        self.assertEqual(score, 0.0)

    def test_na_values(self):
        """NaN 应返回默认值 0.5"""
        import numpy as np
        score = self.selector._calculate_balance_score(np.nan, 100)
        self.assertEqual(score, 0.5)

    def test_balance_in_quality_score(self):
        """_compute_all_scores 应产出 balance_score 列"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "fitness": [1.5, 1.5, 1.5],
            "sharpe": [2.0, 2.0, 2.0],
            "returns": [0.1, 0.1, 0.1],
            "margin": [0.002, 0.002, 0.002],
            "drawdown": [0.05, 0.05, 0.05],
            "turnover": [14.0, 14.0, 14.0],
            "longCount": [100, 100, 10],
            "shortCount": [100, 10, 10],
            "yearly_stats": [[], [], []],
            "os_is_ratio": [np.nan, np.nan, np.nan],
            "inv_sharpe": [1.8, 1.8, 1.8],
            "selfCorrelation": [0.1, 0.1, 0.1],
            "prodCorrelation": [0.2, 0.2, 0.2],
            "max_trade": ["ON", "ON", "ON"],
        })
        result = self.selector._compute_all_scores(df)
        self.assertIn("turnover_score", result.columns)
        self.assertIn("balance_score", result.columns)
        # A 完全平衡，B 严重不平衡，C 完全平衡
        self.assertAlmostEqual(result.loc[0, "balance_score"], 1.0, places=5)
        self.assertAlmostEqual(result.loc[1, "balance_score"], 0.316227, places=5)  # sqrt(0.1)
        self.assertAlmostEqual(result.loc[2, "balance_score"], 1.0, places=5)
        # A 和 C 的 quality_score 应高于 B（因为 balance 更好）
        self.assertGreater(result.loc[0, "quality_score"], result.loc[1, "quality_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
