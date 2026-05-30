import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List

from wqb import NULL, FilterRange

from wqbkit.app.core import AlphaBaseCore
from wqbkit.app.config import config

DEFAULT_REGION = "USA"
COLORS_TO_ASSIGN = [NULL, "RED", "YELLOW", "GREEN", "BLUE", "PURPLE"]
DEFAULT_MAX_WORKERS = config.DEFAULT_DYEING_WORKERS


class AlphaDyeing(AlphaBaseCore):
    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS):
        """初始化 Alpha 染色模块。"""
        super().__init__()
        self.max_workers = max_workers

    def up_alpha_properties(self, alpha_id: str, color: str = NULL) -> str:
        """修改 Alpha 的颜色属性。"""
        try:
            resp = self.wqbs.patch_properties(
                alpha_id,
                color=color,
                log=None
            )

            if resp.ok:
                self.logger.info(f"成功将 Alpha {alpha_id} 的颜色修改为 '{color}'。")
                return color
            else:
                self.logger.error(f"修改 Alpha {alpha_id} 颜色失败，状态码: {resp.status_code}, 信息: {resp.text}")
                return "FAILED"
        except Exception as e:
            self.logger.error(f"修改 Alpha {alpha_id} 颜色时发生异常: {e}")
            return "FAILED"

    def get_submit_alphas(self, start_date: str, end_date: str, region: str) -> List[Dict[str, str]]:
        """按日期范围和区域获取已提交的 REGULAR Alpha 列表。"""
        output: List[Dict[str, str]] = []
        self.logger.info(f"开始获取区域 {region} 从 {start_date} 到 {end_date} 的常规 Alpha...")

        try:
            lo = datetime.fromisoformat(f"{start_date}T00:00:00-04:00")
            hi = datetime.fromisoformat(f"{end_date}T00:00:00-04:00")
            resps = self.wqbs.filter_alphas(
                others=['stage=OS'],
                region=region,
                delay=1,
                type='REGULAR',
                date_created=FilterRange.from_str(f"[{lo.isoformat()}, {hi.isoformat()})"),
                order='-is.sharpe',
            )

            for resp in resps:
                alpha_list = resp.json().get("results", [])
                for alpha in alpha_list:
                    rec = {
                        "id": alpha["id"],
                        "region": alpha["settings"]["region"],
                        "name": alpha.get("name"),
                        "color": alpha.get("color"),
                        "dateSubmitted": alpha["dateSubmitted"],
                    }
                    output.append(rec)

            self.logger.info(f"总共获取了 {len(output)} 个符合条件的 {region} Alpha。")
            return output
        except Exception as e:
            self.logger.error(f"获取 Alpha 列表时发生异常: {e}")
            return []

    def alpha_random_color(self, target_region: str = DEFAULT_REGION, begin_date: str = config.DEFAULT_CONSULTANT_DAY) -> None:
        """对指定区域内的 Alpha 随机均衡分配颜色（多线程）。"""
        end_date_obj = datetime.now() + timedelta(days=1)
        end_date = end_date_obj.strftime("%Y-%m-%d")

        self.logger.info("-" * 40)
        self.logger.info("配置信息:")
        self.logger.info(f"顾问开始日 (脚本起始日期): {begin_date}")
        self.logger.info(f"脚本截止日期: {end_date}")
        self.logger.info(f"目标区域: {target_region}")
        self.logger.info(f"待分配颜色: {['无' if c is None else c for c in COLORS_TO_ASSIGN]}")
        self.logger.info("-" * 40)

        alphas_to_color = self.get_submit_alphas(begin_date, end_date, target_region)
        if not alphas_to_color:
            self.logger.info(f"在指定时间范围和区域 {target_region} 内未找到任何 Alpha，程序结束。")
        else:
            self.logger.info(f"找到 {len(alphas_to_color)} 个 Alpha，准备开始随机均衡分配颜色...")

            random.shuffle(alphas_to_color)
            self.logger.info("Alpha 列表已随机打乱。")

            tasks = []
            color_assignments = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for i, alpha_data in enumerate(alphas_to_color):
                    alpha_id = alpha_data["id"]
                    target_color = COLORS_TO_ASSIGN[i % len(COLORS_TO_ASSIGN)]
                    color_assignments.append(target_color)
                    tasks.append(executor.submit(self.up_alpha_properties, alpha_id, target_color))

            results = [task.result() for task in tasks]

            self.logger.info("=" * 40)
            self.logger.info("所有颜色分配任务已完成。")

            planned_counts = Counter(color_assignments)
            self.logger.info("计划分配的颜色统计:")
            for color, count in planned_counts.items():
                display_color = "无" if color is None else color
                self.logger.info(f"- {display_color}: {count} 个")

            success_counts = Counter(res for res in results if res != "FAILED")
            failed_count = results.count("FAILED")

            self.logger.info("实际成功分配的颜色统计:")
            for color, count in success_counts.items():
                display_color = "无" if color is None else color
                self.logger.info(f"- {display_color}: {count} 个")

            if failed_count > 0:
                self.logger.info(f"失败任务总数: {failed_count} 个")

            self.logger.info("脚本执行完毕。")
            self.logger.info("=" * 40)
