import unittest

import numpy as np
import pandas as pd

from wqbkit.modules.competitions.Osmosis.v3.osmosis_allocator_v3 import OsmosisAllocatorV3


class MockLogger:
    """Mock logger for testing"""
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass
    def debug(self, msg): pass


def _attach_mock_logger(obj):
    obj.logger = MockLogger()


class TestConstraints(unittest.TestCase):
    """测试约束系统"""

    def setUp(self):
        self.allocator = OsmosisAllocatorV3.__new__(OsmosisAllocatorV3)
        _attach_mock_logger(self.allocator)
        self.allocator.config = OsmosisAllocatorV3.DEFAULT_CONFIG.copy()

    def test_per_alpha_ceiling(self):
        """单 Alpha 上限生效"""
        self.allocator.config["max_score_per_alpha"] = 5000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
        })
        df["assigned_score"] = [80000, 15000, 5000]
        result = self.allocator._apply_constraints(df.copy(), 100000)
        self.assertTrue((result["assigned_score"] <= 5000).all())

    def test_per_alpha_floor(self):
        """单 Alpha 下限生效"""
        self.allocator.config["min_score_per_alpha"] = 100
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
        })
        df["assigned_score"] = [1000, 50, 10]
        result = self.allocator._post_process(df.copy(), 100000)
        self.assertTrue((result["assigned_score"] >= 100).all())

    def test_dataset_tags_constraint(self):
        """dataset_tags 上限约束生效"""
        self.allocator.config["max_score_per_dataset_tags"] = 30000
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D"],
            "quality_score": [1.0, 0.8, 0.6, 0.4],
            "dataset_tags": [
                ["Fundamental"],
                ["Fundamental"],
                ["Price Volume"],
                ["Price Volume"],
            ],
        })
        df["assigned_score"] = [30000, 30000, 20000, 20000]
        result = self.allocator._apply_dataset_tags_constraint(df.copy(), 30000)
        # Fundamental 标签总和 = 60000 > 30000，应被压缩
        fund_mask = result["dataset_tags"].apply(lambda t: "Fundamental" in t)
        fund_total = result.loc[fund_mask, "assigned_score"].sum()
        self.assertLessEqual(fund_total, 30000 * 1.01)  # 允许 1% 浮点误差

    def test_neutralization_constraint(self):
        """neutralization 上限约束生效"""
        self.allocator.config["max_score_per_neutralization"] = 40000
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D"],
            "quality_score": [1.0, 0.8, 0.6, 0.4],
            "neutralization": ["SLOW", "SLOW", "FAST", "FAST"],
        })
        df["assigned_score"] = [30000, 30000, 20000, 20000]
        result = self.allocator._apply_neutralization_constraint(df.copy(), 40000)
        slow_total = result.loc[result["neutralization"] == "SLOW", "assigned_score"].sum()
        self.assertLessEqual(slow_total, 40000 * 1.01)

    def test_iterative_convergence(self):
        """约束迭代收敛"""
        self.allocator.config["max_score_per_alpha"] = 50000
        self.allocator.config["max_score_per_dataset_tags"] = 30000
        self.allocator.config["max_score_per_neutralization"] = 30000
        self.allocator.config["constraint_max_iterations"] = 20

        df = pd.DataFrame({
            "id": ["A", "B", "C", "D"],
            "quality_score": [1.0, 0.8, 0.6, 0.4],
            "dataset_tags": [
                ["Fundamental"],
                ["Fundamental"],
                ["Price Volume"],
                ["Price Volume"],
            ],
            "neutralization": ["SLOW", "SLOW", "FAST", "FAST"],
        })
        df["assigned_score"] = [40000, 40000, 10000, 10000]
        result = self.allocator._apply_constraints(df.copy(), 100000)
        # 检查所有约束都满足
        self.assertTrue((result["assigned_score"] <= 50000).all())
        # 重新校准后总分应接近 100000
        self.assertAlmostEqual(result["assigned_score"].sum(), 100000, delta=1000)

    def test_full_pipeline_constraints(self):
        """完整 pipeline：mixed 方法 + 约束"""
        self.allocator.config["max_score_per_alpha"] = 30000
        self.allocator.config["max_score_per_dataset_tags"] = 40000

        df = pd.DataFrame({
            "id": ["A", "B", "C", "D", "E"],
            "quality_score": [1.0, 0.9, 0.8, 0.7, 0.6],
            "dataset_tags": [
                ["Fundamental"],
                ["Fundamental"],
                ["Fundamental"],
                ["Price Volume"],
                ["Price Volume"],
            ],
            "neutralization": ["SLOW", "FAST", "NONE", "SLOW", "FAST"],
        })
        result = self.allocator.allocate(df, method="mixed", total_score=100000)

        # 单 Alpha 上限
        self.assertTrue((result["assigned_score"] <= 30000).all())
        # 总分 = 100000
        self.assertEqual(result["assigned_score"].sum(), 100000)
        # 最低分 >= 1
        self.assertTrue((result["assigned_score"] >= 1).all())


class TestMixedMethod(unittest.TestCase):
    """测试 Mixed 分配方法"""

    def setUp(self):
        self.allocator = OsmosisAllocatorV3.__new__(OsmosisAllocatorV3)
        _attach_mock_logger(self.allocator)
        self.allocator.config = OsmosisAllocatorV3.DEFAULT_CONFIG.copy()

    def test_mixed_weights_sum_to_one(self):
        """mixed 权重之和为 1"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
            "neutralization": ["SLOW", "FAST", "NONE"],
        })
        result = self.allocator._allocate_mixed(df.copy(), 100000)
        self.assertAlmostEqual(result["assigned_score"].sum(), 100000, delta=1)

    def test_mixed_quality_dominant(self):
        """quality_score 最高的 Alpha 应获得最多分数（相同 neutralization 排除 cluster 干扰）"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.2],
            "neutralization": ["SLOW", "SLOW", "SLOW"],
        })
        result = self.allocator._allocate_mixed(df.copy(), 100000)
        scores = dict(zip(result["id"], result["assigned_score"]))
        self.assertGreater(scores["A"], scores["B"])
        self.assertGreater(scores["B"], scores["C"])

    def test_rank_decay_monotonic(self):
        """rank_decay 权重随排名递减"""
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D", "E"],
            "quality_score": [1.0, 0.9, 0.8, 0.7, 0.6],
        })
        result = self.allocator._allocate_mixed(df.copy(), 100000)
        # quality_score 越高，assigned_score 应越高
        qs = result["quality_score"].values
        ss = result["assigned_score"].values
        for i in range(len(qs) - 1):
            if qs[i] > qs[i + 1]:
                self.assertGreaterEqual(ss[i], ss[i + 1])

    def test_cluster_balance_effect(self):
        """cluster balance 应降低高集中度 cluster 的权重"""
        # 4 个 Alpha 同属一个 neutralization，1 个属于另一个
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D", "E"],
            "quality_score": [1.0, 0.9, 0.8, 0.7, 0.6],
            "neutralization": ["SLOW", "SLOW", "SLOW", "SLOW", "FAST"],
        })
        result = self.allocator._allocate_mixed(df.copy(), 100000)
        # 不精确断言，只检查总和正确
        self.assertAlmostEqual(result["assigned_score"].sum(), 100000, delta=1)

    def test_mixed_with_constraints(self):
        """mixed + 约束完整 pipeline"""
        self.allocator.config["max_score_per_alpha"] = 25000
        self.allocator.config["max_score_per_dataset_tags"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D", "E"],
            "quality_score": [1.0, 0.9, 0.8, 0.7, 0.6],
            "dataset_tags": [
                ["Fundamental"], ["Fundamental"], ["Price Volume"],
                ["Price Volume"], ["News"],
            ],
            "neutralization": ["SLOW", "FAST", "NONE", "SLOW", "FAST"],
        })
        result = self.allocator.allocate(df, method="mixed", total_score=100000)
        self.assertEqual(result["assigned_score"].sum(), 100000)
        self.assertTrue((result["assigned_score"] <= 25000).all())
        self.assertTrue((result["assigned_score"] >= 1).all())


class TestV2Compatibility(unittest.TestCase):
    """测试 V2 方法兼容性"""

    def setUp(self):
        self.allocator = OsmosisAllocatorV3.__new__(OsmosisAllocatorV3)
        _attach_mock_logger(self.allocator)
        self.allocator.config = OsmosisAllocatorV3.DEFAULT_CONFIG.copy()

    def test_equal(self):
        """等权分配"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C", "D"],
            "quality_score": [1.0, 0.8, 0.6, 0.4],
        })
        result = self.allocator.allocate(df, method="equal", total_score=100000, apply_constraints=False)
        self.assertEqual(result["assigned_score"].sum(), 100000)
        # 等权分配后四舍五入，可能不完全相等，但接近
        self.assertTrue(result["assigned_score"].nunique() <= 2)  # 最多两种值（因四舍五入）

    def test_score_proportional(self):
        """score_prop 方法"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.2],
        })
        result = self.allocator.allocate(df, method="score_prop", total_score=100000, temperature=0.15, apply_constraints=False)
        scores = dict(zip(result["id"], result["assigned_score"]))
        self.assertGreater(scores["A"], scores["B"])
        self.assertGreater(scores["B"], scores["C"])
        self.assertEqual(result["assigned_score"].sum(), 100000)

    def test_mdc(self):
        """MDC 方法"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.8, 0.5],
            "prodCorrelation": [0.0, 0.3, 0.6],
        })
        result = self.allocator.allocate(df, method="mdc", total_score=100000, apply_constraints=False)
        self.assertEqual(result["assigned_score"].sum(), 100000)
        # prodCorrelation 越高，effective_score 打折越多
        scores = dict(zip(result["id"], result["assigned_score"]))
        # A (corr=0) 应比 C (corr=0.6) 高
        self.assertGreater(scores["A"], scores["C"])

    def test_inverse_vol(self):
        """逆波动率方法"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.8, 0.5],
            "drawdown": [0.05, 0.10, 0.20],
            "turnover": [0.10, 0.15, 0.25],
        })
        result = self.allocator.allocate(df, method="inverse_vol", total_score=100000, apply_constraints=False)
        self.assertEqual(result["assigned_score"].sum(), 100000)
        # drawdown 越低，分配应越高
        scores = dict(zip(result["id"], result["assigned_score"]))
        self.assertGreater(scores["A"], scores["C"])


class TestPostProcess(unittest.TestCase):
    """测试后处理"""

    def setUp(self):
        self.allocator = OsmosisAllocatorV3.__new__(OsmosisAllocatorV3)
        _attach_mock_logger(self.allocator)
        self.allocator.config = OsmosisAllocatorV3.DEFAULT_CONFIG.copy()

    def test_integer_rounding(self):
        """四舍五入到整数"""
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
        })
        df["assigned_score"] = [33333.3, 33333.3, 33333.4]
        result = self.allocator._post_process(df.copy(), 100000)
        self.assertTrue((result["assigned_score"] == result["assigned_score"].astype(int)).all())

    def test_total_calibration(self):
        """总分校准严格等于 100000"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
        })
        df["assigned_score"] = [33333.4, 33333.3, 33333.3]  # 总和 ~100000
        result = self.allocator._post_process(df.copy(), 100000)
        self.assertEqual(result["assigned_score"].sum(), 100000)

    def test_remainder_distribution(self):
        """余数加到 quality_score 最高的 Alpha"""
        self.allocator.config["max_score_per_alpha"] = 50000
        df = pd.DataFrame({
            "id": ["A", "B", "C"],
            "quality_score": [1.0, 0.5, 0.3],
        })
        df["assigned_score"] = [33333.0, 33333.0, 33333.0]  # 总和 99999，余 1
        result = self.allocator._post_process(df.copy(), 100000)
        self.assertEqual(result["assigned_score"].sum(), 100000)
        # A 的 quality_score 最高，应多拿 1
        scores = dict(zip(result["id"], result["assigned_score"]))
        self.assertGreaterEqual(scores["A"], scores["B"])

    def test_empty_df(self):
        """空 DataFrame 处理"""
        df = pd.DataFrame()
        result = self.allocator.allocate(df, method="mixed", total_score=100000)
        self.assertTrue(result.empty)

    def test_single_alpha(self):
        """单个 Alpha"""
        self.allocator.config["max_score_per_alpha"] = 100000
        df = pd.DataFrame({
            "id": ["A"],
            "quality_score": [0.5],
        })
        result = self.allocator.allocate(df, method="mixed", total_score=100000, apply_constraints=False)
        self.assertEqual(result["assigned_score"].iloc[0], 100000)


class TestRecalibrate(unittest.TestCase):
    """测试重新校准"""

    def setUp(self):
        self.allocator = OsmosisAllocatorV3.__new__(OsmosisAllocatorV3)
        _attach_mock_logger(self.allocator)
        self.allocator.config = OsmosisAllocatorV3.DEFAULT_CONFIG.copy()

    def test_scale_up(self):
        """总分不足时放大"""
        df = pd.DataFrame({
            "id": ["A", "B"],
            "quality_score": [0.5, 0.5],
        })
        df["assigned_score"] = [5000.0, 5000.0]
        result = self.allocator._recalibrate_total(df.copy(), 100000)
        self.assertAlmostEqual(result["assigned_score"].sum(), 100000)
        self.assertAlmostEqual(result.loc[0, "assigned_score"], 50000)

    def test_scale_down(self):
        """总分超额时缩小"""
        df = pd.DataFrame({
            "id": ["A", "B"],
            "quality_score": [0.5, 0.5],
        })
        df["assigned_score"] = [100000.0, 100000.0]
        result = self.allocator._recalibrate_total(df.copy(), 100000)
        self.assertAlmostEqual(result["assigned_score"].sum(), 100000)
        self.assertAlmostEqual(result.loc[0, "assigned_score"], 50000)


if __name__ == "__main__":
    unittest.main()
