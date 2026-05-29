"""
OsmosisRunnerV3 测试套件

运行方式:
    cd /home/worldquant/wqb/Code2.0
    /root/anaconda3/envs/worldquant/bin/python -m pytest modules/competitions/Osmosis/v3/tests/test_runner_v3.py -v
"""

import logging
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from wqbkit.modules.competitions.Osmosis.v3.osmosis_runner_v3 import OsmosisRunnerV3


class MockLogger:
    def debug(self, msg, *args, **kwargs): pass
    def info(self, msg, *args, **kwargs): pass
    def warning(self, msg, *args, **kwargs): pass
    def error(self, msg, *args, **kwargs): pass


def _make_df(n=5, with_score=False):
    """构造测试 DataFrame"""
    data = {
        "id": [f"A{i}" for i in range(n)],
        "type": ["REGULAR"] * n,
        "sharpe": [2.0 - i * 0.1 for i in range(n)],
        "fitness": [1.5 - i * 0.05 for i in range(n)],
        "turnover": [14.0] * n,
        "assigned_score": [int(100000 / n)] * n if with_score else [0] * n,
    }
    return pd.DataFrame(data)


class TestOsmosisRunnerV3Config(unittest.TestCase):
    """测试配置系统"""

    def test_default_config(self):
        """默认配置应包含所有关键参数"""
        runner = OsmosisRunnerV3.__new__(OsmosisRunnerV3)
        runner.config = OsmosisRunnerV3.DEFAULT_CONFIG.copy()

        self.assertEqual(runner.config["regions"], ["USA", "GLB", "EUR", "ASI", "IND"])
        self.assertEqual(runner.config["min_alpha_count"], 10)
        self.assertEqual(runner.config["total_score"], 100000)
        self.assertEqual(runner.config["allocation_method"], "mixed")
        self.assertTrue(runner.config["apply_constraints"])

    def test_custom_config_override(self):
        """自定义配置应覆盖默认值"""
        runner = OsmosisRunnerV3(config={
            "regions": ["USA"],
            "allocation_method": "equal",
            "min_alpha_count": 5,
        })
        self.assertEqual(runner.config["regions"], ["USA"])
        self.assertEqual(runner.config["allocation_method"], "equal")
        self.assertEqual(runner.config["min_alpha_count"], 5)
        self.assertEqual(runner.config["total_score"], 100000)  # 未覆盖


class TestOsmosisRunnerV3Run(unittest.TestCase):
    """测试主流程"""

    def setUp(self):
        self.runner = OsmosisRunnerV3.__new__(OsmosisRunnerV3)
        self.runner.config = {
            **OsmosisRunnerV3.DEFAULT_CONFIG,
            "regions": ["TEST1", "TEST2"],
            "min_alpha_count": 3,
        }
        self.runner.logger = MockLogger()

        # Mock 三个组件
        self.runner.selector = MagicMock()
        self.runner.allocator = MagicMock()
        self.runner.clearer = MagicMock()

    def test_run_basic_pipeline(self):
        """基本流程：select → allocate → report，不 update"""
        df_selected = _make_df(n=5)
        df_alloc = _make_df(n=5, with_score=True)
        self.runner.selector.select.return_value = df_selected
        self.runner.allocator.allocate.return_value = df_alloc

        results = self.runner.run(update=False)

        self.assertEqual(len(results), 2)  # 两个 region
        for r in results:
            self.assertEqual(r["status"], "成功")
            self.assertEqual(r["count"], 5)

        # 不应调用 clear/update
        self.runner.clearer.clear.assert_not_called()
        self.runner.allocator.update_osmosis_points.assert_not_called()

    def test_run_with_update(self):
        """update=True 时应先 clear 再 update"""
        df_selected = _make_df(n=5)
        df_alloc = _make_df(n=5, with_score=True)
        self.runner.selector.select.return_value = df_selected
        self.runner.allocator.allocate.return_value = df_alloc
        self.runner.clearer.clear.return_value = {"success": 5, "failed": 0, "protected": 0}
        self.runner.allocator.update_osmosis_points.return_value = {
            "A0": 200, "A1": 200, "A2": 200, "A3": 200, "A4": 200,
        }

        results = self.runner.run(update=True)

        self.assertEqual(len(results), 2)
        # 每个 region 都应调用 clear + update
        self.assertEqual(self.runner.clearer.clear.call_count, 2)
        self.assertEqual(self.runner.allocator.update_osmosis_points.call_count, 2)

    def test_run_preview_no_api_calls(self):
        """update=False 时不应调用任何 clear/update API"""
        df_selected = _make_df(n=5)
        df_alloc = _make_df(n=5, with_score=True)
        self.runner.selector.select.return_value = df_selected
        self.runner.allocator.allocate.return_value = df_alloc

        results = self.runner.run(update=False)

        self.runner.clearer.clear.assert_not_called()
        self.runner.allocator.update_osmosis_points.assert_not_called()

    def test_run_region_skip_insufficient(self):
        """Alpha 数量不足时应跳过"""
        df_selected = _make_df(n=2)  # 不足 min_alpha_count=3
        self.runner.selector.select.return_value = df_selected

        results = self.runner.run(update=False)

        for r in results:
            self.assertEqual(r["status"], "跳过")
            self.assertEqual(r["count"], 2)
        # allocator 不应被调用
        self.runner.allocator.allocate.assert_not_called()

    def test_run_region_selector_exception(self):
        """Selector 异常应被隔离，不影响其他 region"""
        self.runner.selector.select.side_effect = [
            Exception("Selector failed"),  # TEST1 失败
            _make_df(n=5),                 # TEST2 成功
        ]
        self.runner.allocator.allocate.return_value = _make_df(n=5, with_score=True)

        results = self.runner.run(update=False)

        self.assertEqual(results[0]["status"], "Selector异常")
        self.assertEqual(results[1]["status"], "成功")

    def test_run_region_allocator_exception(self):
        """Allocator 异常应被隔离"""
        self.runner.selector.select.return_value = _make_df(n=5)
        self.runner.allocator.allocate.side_effect = Exception("Allocator failed")

        results = self.runner.run(update=False)

        for r in results:
            self.assertEqual(r["status"], "Allocator异常")

    def test_run_single_region(self):
        """单 region 运行"""
        self.runner.config["regions"] = ["USA"]
        df_selected = _make_df(n=5)
        df_alloc = _make_df(n=5, with_score=True)
        self.runner.selector.select.return_value = df_selected
        self.runner.allocator.allocate.return_value = df_alloc

        results = self.runner.run(update=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["region"], "USA")

    def test_run_update_with_failures(self):
        """update 时部分 Alpha 失败应记录在结果中"""
        df_selected = _make_df(n=5)
        df_alloc = _make_df(n=5, with_score=True)
        self.runner.selector.select.return_value = df_selected
        self.runner.allocator.allocate.return_value = df_alloc
        self.runner.clearer.clear.return_value = {"success": 5, "failed": 0, "protected": 0}
        self.runner.allocator.update_osmosis_points.return_value = {
            "A0": 200, "A1": 404, "A2": 200, "A3": 500, "A4": 200,
        }

        results = self.runner.run(update=True)

        failed = results[0].get("failed_alphas", [])
        self.assertEqual(len(failed), 2)  # A1(404), A3(500)

    def test_make_region_result(self):
        """_make_region_result 应正确构造结果字典"""
        result = OsmosisRunnerV3._make_region_result(
            region="USA", status="成功", count=10, total=100000,
            failed_alphas=["A1"], max_score=15000, min_score=1000,
        )
        self.assertEqual(result["region"], "USA")
        self.assertEqual(result["status"], "成功")
        self.assertEqual(result["count"], 10)
        self.assertEqual(result["total"], 100000)
        self.assertEqual(result["failed_alphas"], ["A1"])
        self.assertEqual(result["max_score"], 15000)
        self.assertEqual(result["min_score"], 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
