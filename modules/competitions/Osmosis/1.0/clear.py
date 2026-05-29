import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional

sys.path.append("/home/worldquant/wqb/Code")

from wqbkit.app.core.alpha_base_core import AlphaBaseCore

API_BASE_URL = "https://api.worldquantbrain.com"
ALPHAS_URL = f"{API_BASE_URL}/alphas"
USERS_SELF_URL = f"{API_BASE_URL}/users/self"
DEFAULT_BATCH_SIZE = 100
DEFAULT_ALPHA_LIMIT = 1000
DEFAULT_REGION = "GLB"
MAX_WORKERS = 10
TOBE_CONSULTANT_DAY = "2025-04-19"

logger = logging.getLogger(__name__)


def up_alpha_properties_to_clear(
    session: AlphaBaseCore,
    alpha_id: str,
    old_osmosis_points: Optional[float],
) -> str:
    params = {"osmosisPoints": None}
    response = session.patch(f"{ALPHAS_URL}/{alpha_id}", json=params)

    if response.status_code == 200:
        logger.info(f"成功清除 Alpha {alpha_id} 的分数 (原分数: {old_osmosis_points})。")
        return "SUCCESS"

    logger.error(
        f"清除 Alpha {alpha_id} 分数失败，状态码: {response.status_code}, 信息: {response.text}"
    )
    return "FAILED"


def get_colored_alphas_in_date_range(
    session: AlphaBaseCore,
    start_date: str,
    end_date: str,
    region: str,
    alpha_num_limit: int = DEFAULT_ALPHA_LIMIT,
) -> List[dict]:
    colored_alphas: List[dict] = []
    logger.info(f"开始查找从 {start_date} 到 {end_date} 所有已设置分数的常规 Alpha...")

    for offset in range(0, alpha_num_limit, DEFAULT_BATCH_SIZE):
        logger.info(f"正在扫描第 {offset} 到 {offset + DEFAULT_BATCH_SIZE} 个 alpha...")
        if region == "ALL":
            url_e = (
                f"{USERS_SELF_URL}/alphas?limit={DEFAULT_BATCH_SIZE}&offset={offset}"
                f"&status!=UNSUBMITTED&status!=IS_FAIL&type!=SUPER&hidden=false"
                f"&dateSubmitted>={start_date}T00:00:00-04:00"
                f"&dateSubmitted<{end_date}T00:00:00-04:00"
            )
        else:
            url_e = (
                f"{USERS_SELF_URL}/alphas?limit={DEFAULT_BATCH_SIZE}&offset={offset}"
                f"&status!=UNSUBMITTED&status!=IS_FAIL&type!=SUPER&hidden=false&settings.region={region}"
                f"&dateSubmitted>={start_date}T00:00:00-04:00"
                f"&dateSubmitted<{end_date}T00:00:00-04:00"
            )
        try:
            response = session.get(url_e)
            response.raise_for_status()
            alpha_list = response.json().get("results", [])

            if not alpha_list:
                logger.info("已扫描完所有符合条件的 Alpha。")
                break

            for alpha in alpha_list:
                if alpha.get("osmosisPoints") is not None:
                    colored_alphas.append(
                        {
                            "id": alpha["id"],
                            "osmosisPoints": alpha["osmosisPoints"],
                        }
                    )
        except Exception as e:
            logger.error(f"获取 alpha 时发生异常: {e}")
            resp = session.get(USERS_SELF_URL)
            if resp.status_code != 200:
                logger.error(f"用户会话可能已过期，状态码: {resp.status_code}")
            break

    logger.info(f"查找完毕，共找到 {len(colored_alphas)} 个需要清除分数的 Alpha。")
    return colored_alphas


if __name__ == "__main__":
    core = AlphaBaseCore()

    begin_date = TOBE_CONSULTANT_DAY
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    region = DEFAULT_REGION

    logger.info("-" * 50)
    logger.info("本脚本将查找并清除指定日期范围内的常规 Alpha 分数。")
    logger.info(f"顾问开始日 (脚本起始日期): {begin_date}")
    logger.info(f"脚本截止日期: {end_date}")
    logger.info(f"区域: {region}")
    logger.info("-" * 50)

    alphas_to_clear = get_colored_alphas_in_date_range(core, begin_date, end_date, region)

    if not alphas_to_clear:
        logger.info("在指定日期范围内未找到任何设置了分数的 Alpha，程序结束。")
    else:
        logger.info("准备开始清除分数...")

        tasks = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for alpha_data in alphas_to_clear:
                alpha_id = alpha_data["id"]
                old_osmosis_points = alpha_data["osmosisPoints"]
                tasks.append(
                    executor.submit(up_alpha_properties_to_clear, core, alpha_id, old_osmosis_points)
                )

        results = [task.result() for task in tasks]

        success_count = results.count("SUCCESS")
        failed_count = results.count("FAILED")

        logger.info("所有分数清除任务已完成。")
        logger.info(f"成功清除分数的 Alpha 数量: {success_count}")
        logger.info(f"失败的任务数量: {failed_count}")
        logger.info("脚本执行完毕。")
