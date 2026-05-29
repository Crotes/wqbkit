"""
OsmosisClearV3 测试套件

运行方式:
    cd /home/worldquant/wqb/Code2.0
    /root/anaconda3/envs/worldquant/bin/python -m pytest modules/competitions/Osmosis/v3/tests/test_clear_v3.py -v
"""

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from wqbkit.modules.competitions.Osmosis.v3.osmosis_clear_v3 import OsmosisClearV3


class MockLogger:
    def debug(self, msg, *args, **kwargs): pass
    def info(self, msg, *args, **kwargs): pass
    def warning(self, msg, *args, **kwargs): pass
    def error(self, msg, *args, **kwargs): pass


def _attach_mock_logger(obj):
    obj.logger = MockLogger()


class TestOsmosisClearV3Config(unittest.TestCase):
    """测试配置系统"""

    def test_default_config(self):
        """默认配置应包含所有关键参数"""
        clear = OsmosisClearV3.__new__(OsmosisClearV3)
        _attach_mock_logger(clear)
        clear.config = OsmosisClearV3.DEFAULT_CONFIG.copy()

        self.assertEqual(clear.config["batch_size"], 100)
        self.assertEqual(clear.config["alpha_limit"], 2000)
        self.assertEqual(clear.config["max_workers"], 10)
        self.assertEqual(clear.config["default_start_date"], "2025-01-01")

    def test_custom_config(self):
        """自定义配置应覆盖默认值"""
        clear = OsmosisClearV3.__new__(OsmosisClearV3)
        _attach_mock_logger(clear)
        clear.config = {**OsmosisClearV3.DEFAULT_CONFIG, "batch_size": 50, "max_workers": 5}

        self.assertEqual(clear.config["batch_size"], 50)
        self.assertEqual(clear.config["max_workers"], 5)
        self.assertEqual(clear.config["alpha_limit"], 2000)  # 未覆盖的保持默认


class TestOsmosisClearV3Scan(unittest.TestCase):
    """测试扫描功能"""

    def setUp(self):
        self.clearer = OsmosisClearV3.__new__(OsmosisClearV3)
        _attach_mock_logger(self.clearer)
        self.clearer.config = OsmosisClearV3.DEFAULT_CONFIG.copy()

    def _make_mock_response(self, alphas):
        """构造 mock API 响应"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": alphas, "count": len(alphas)}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_scan_finds_targets(self, mock_get):
        """scan 应正确识别已设置分数的 Alpha"""
        # 第一次返回数据，第二次返回空（模拟分页结束）
        mock_get.side_effect = [
            self._make_mock_response([
                {"id": "A1", "osmosisPoints": 5000, "settings": {"region": "USA"}, "type": "REGULAR"},
                {"id": "A2", "osmosisPoints": None, "settings": {"region": "USA"}, "type": "REGULAR"},
                {"id": "A3", "osmosisPoints": 3000, "settings": {"region": "USA"}, "type": "SUPER"},
            ]),
            self._make_mock_response([]),
        ]

        targets = self.clearer.scan(region="USA", dry_run=True)

        self.assertEqual(len(targets), 2)
        ids = [t["id"] for t in targets]
        self.assertIn("A1", ids)
        self.assertIn("A3", ids)
        self.assertNotIn("A2", ids)  # 未设置分数的不应被扫描到

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_scan_respects_region(self, mock_get):
        """scan 应正确构造 region 过滤参数"""
        mock_get.return_value = self._make_mock_response([])

        self.clearer.scan(region="EUR")

        call_url = mock_get.call_args[0][0]
        self.assertIn("settings.region=EUR", call_url)

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_scan_respects_type_filter(self, mock_get):
        """scan 应正确构造 type 过滤参数"""
        mock_get.return_value = self._make_mock_response([])

        self.clearer.scan(type_filter="REGULAR")

        call_url = mock_get.call_args[0][0]
        self.assertIn("type=REGULAR", call_url)

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_scan_empty_results(self, mock_get):
        """没有结果时应返回空列表"""
        mock_get.return_value = self._make_mock_response([])

        targets = self.clearer.scan()
        self.assertEqual(len(targets), 0)


class TestOsmosisClearV3Clear(unittest.TestCase):
    """测试清除功能"""

    def setUp(self):
        self.clearer = OsmosisClearV3.__new__(OsmosisClearV3)
        _attach_mock_logger(self.clearer)
        self.clearer.config = OsmosisClearV3.DEFAULT_CONFIG.copy()

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.patch")
    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_clear_success(self, mock_get, mock_patch):
        """clear 应成功清除目标 Alpha"""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {
                    "results": [
                        {"id": "A1", "osmosisPoints": 5000, "settings": {"region": "USA"}, "type": "REGULAR"},
                        {"id": "A2", "osmosisPoints": 3000, "settings": {"region": "USA"}, "type": "REGULAR"},
                    ],
                    "count": 2,
                },
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"results": [], "count": 2},
                raise_for_status=MagicMock(),
            ),
        ]
        mock_patch.return_value = MagicMock(status_code=200)

        result = self.clearer.clear(region="USA")

        self.assertEqual(result["success"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["protected"], 0)
        self.assertEqual(mock_patch.call_count, 2)

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.patch")
    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_clear_with_protection(self, mock_get, mock_patch):
        """protect_ids 应保护指定 Alpha 不被清除"""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {
                    "results": [
                        {"id": "A1", "osmosisPoints": 5000, "settings": {"region": "USA"}, "type": "REGULAR"},
                        {"id": "A2", "osmosisPoints": 3000, "settings": {"region": "USA"}, "type": "REGULAR"},
                    ],
                    "count": 2,
                },
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"results": [], "count": 2},
                raise_for_status=MagicMock(),
            ),
        ]
        mock_patch.return_value = MagicMock(status_code=200)

        result = self.clearer.clear(region="USA", protect_ids=["A1"])

        self.assertEqual(result["success"], 1)
        self.assertEqual(result["protected"], 1)
        # 只清除了 A2
        mock_patch.assert_called_once()

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.patch")
    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_clear_dry_run(self, mock_get, mock_patch):
        """dry_run 不应调用 patch API"""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {
                    "results": [
                        {"id": "A1", "osmosisPoints": 5000, "settings": {"region": "USA"}, "type": "REGULAR"},
                    ],
                    "count": 1,
                },
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"results": [], "count": 1},
                raise_for_status=MagicMock(),
            ),
        ]

        result = self.clearer.clear(region="USA", dry_run=True)

        self.assertEqual(result["dry_run"], 1)
        self.assertEqual(result["success"], 0)
        mock_patch.assert_not_called()

    @patch("modules.competitions.Osmosis.v3.osmosis_clear_v3.AlphaBaseCore.get")
    def test_clear_no_targets(self, mock_get):
        """没有目标时应直接返回"""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "count": 0},
            raise_for_status=MagicMock(),
        )

        result = self.clearer.clear()

        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failed"], 0)

    def test_clear_one_success(self):
        """clear_one 成功时应返回 SUCCESS"""
        with patch.object(
            self.clearer, "patch", return_value=MagicMock(status_code=200)
        ) as mock_patch:
            result = self.clearer.clear_one("A1", 5000)
            self.assertEqual(result, "SUCCESS")
            mock_patch.assert_called_once_with(
                "https://api.worldquantbrain.com/alphas/A1",
                json={"osmosisPoints": None},
            )

    def test_clear_one_failure(self):
        """clear_one 失败时应返回 FAILED"""
        with patch.object(
            self.clearer, "patch", return_value=MagicMock(status_code=404)
        ):
            result = self.clearer.clear_one("A1", 5000)
            self.assertEqual(result, "FAILED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
