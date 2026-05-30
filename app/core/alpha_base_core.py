"""
WorldQuant Brain Alpha 交互的核心功能。
包括认证、带重试的请求处理和基本的 Alpha 管理。
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import requests
from wqb import NULL, WQBSession, FilterRange

from wqbkit.app.config import config
from wqbkit.app.core.decorators import retry_decorator
from wqbkit.app.core.logger import get_logger
from wqbkit.app.core.wqb_urls import URL_USERS_SELF_ACTIVITIES_PYRAMID_ALPHAS

RETRY_AFTER_MIN_SECONDS: int = 10

class AlphaBaseCore:
    """WorldQuant Brain Alpha 交互的基类。"""

    def __init__(self) -> None:
        """初始化基类：加载认证信息并建立 WQB 登录会话。"""
        self._username = config.WQB_USERNAME
        self._password = config.WQB_PASSWORD
        self.logger = get_logger(self.__class__.__name__)
        self.wqbs = self._login()

    @retry_decorator()
    def _login(self) -> WQBSession:
        """登录并获取WQB会话"""
        # 创建新session
        wqbs = WQBSession(
            wqb_auth=(self._username, self._password),
            logger=self.logger
        )
        resp = wqbs.auth_request()
        
        if resp.status_code != 201:
            # 装饰器会捕获异常并记录，这里只需抛出
            raise ConnectionError(f'登录失败: {resp.status_code}')
            
        user_id = resp.json()['user']['id']
        self.logger.info(f'登录成功, 用户ID: {user_id}')

        return wqbs

    def _handle_request_with_retry(self, method_name: str, *args, **kwargs) -> requests.Response:
        """统一处理带有重试机制的请求（针对 429 Too Many Requests）"""
        method = getattr(self.wqbs, method_name)
        while True:
            response = method(*args, **kwargs)
            retry_after = float(response.headers.get("Retry-After", 0))
            if retry_after == 0:
                break
            
            if response.status_code == 429:
                ti = max(RETRY_AFTER_MIN_SECONDS, retry_after)
                self.logger.info(f'429错误, {method_name} 等待 {ti} 秒({ti//60} 分 {ti%60} 秒)')
                time.sleep(ti)
                continue
            
            time.sleep(max(10, retry_after))
        
        return response

    def get(self, url: str) -> requests.Response:
        """发送 GET 请求，自动处理 429 重试"""
        response = self._handle_request_with_retry('get', url)
        response.raise_for_status()
        return response

    def post(self, url: str, data: Dict[str, Any]) -> requests.Response:
        """发送 POST 请求，自动处理 429 重试"""
        response = self.wqbs.post(url, json=data)
        response.raise_for_status()
        return response
    
    def delete(self, url: str) -> requests.Response:
        """发送 DELETE 请求，自动处理 429 重试"""
        response = self.wqbs.delete(url)
        response.raise_for_status()
        return response

    def patch(self, url: str, json: Dict[str, Any]) -> requests.Response:
        """发送 PATCH 请求，自动处理 429 重试"""
        response = self._handle_request_with_retry('patch', url, json=json)
        response.raise_for_status()
        return response

    @retry_decorator()
    def update_alpha_metadata(
        self,
        alpha_id: str,
        tag: str | list = None,
    ) -> None:
        """更新alpha元数据

        Args:
            alpha_id: Alpha ID
            tag: Alpha标签
        """
        try:
            if not isinstance(tag, list):
                tags = [tag]
            else:
                tags = tag
            
            resp = self._handle_request_with_retry(
                'patch_properties',
                alpha_id,
                tags=tags,
                log=None
            )
            
            if resp.ok:
                self.logger.info(f"{alpha_id}更新tag成功")
            else:
                error_msg = resp.json().get('error', 'Unknown error')
                self.logger.warning(f"{alpha_id}更新tag失败: {resp.status_code} - {error_msg}")
        except Exception as e:
            # 装饰器会捕获并重试
            raise Exception(f"{alpha_id}更新失败: {str(e)}") from e

    @retry_decorator()
    def clear_alpha_metadata(self, alpha_id: str) -> None:
        """清除alpha元数据

        Args:
            alpha_id: Alpha ID
        """
        try:
            resp = self._handle_request_with_retry(
                'patch_properties',
                alpha_id,
                tags=NULL,
                color=NULL,
            )
            
            if resp.ok:
                self.logger.info(f"{alpha_id}清除成功")
            else:
                error_msg = resp.json().get('error', 'Unknown error')
                self.logger.warning(f"{alpha_id}清除失败: {resp.status_code} - {error_msg}")
        except Exception as e:
            raise Exception(f"{alpha_id}清除失败: {str(e)}") from e

    @retry_decorator()
    def hidden_alpha(self, alpha_ids: str|list) -> None:
        """隐藏alpha

        Args:
            alpha_id: Alpha ID
        """
        if not isinstance(alpha_ids, list):
            alpha_ids = [alpha_ids]

        for alpha_id in alpha_ids:
            try:
                self._handle_request_with_retry(
                    'patch_properties',
                    alpha_id,
                    hidden=True,
                    log=None
                )
                self.logger.info(f"{alpha_id}隐藏成功")
            except Exception as e:
                self.logger.error(f"{alpha_id}隐藏失败: {str(e)}")
                raise

    def get_operators(self) -> None:
        """加载 WQB 官方算子列表，筛选出 REGULAR scope 的算子集合。"""
        resp = self.wqbs.search_operators(log=None)
        self.operators = {item['name'] for item in resp.json() if 'REGULAR' in item['scope']}

    def get_current_quarter_range(self) -> tuple[datetime, datetime]:
        """
        获取当前季度的起点和终点
        返回 (start_date, end_date) 两个 datetime 对象，格式如 2025-01-28T00:00:00-05:00
        """
        tz = timezone(timedelta(hours=-5))  # UTC-05:00
        now = datetime.now(tz)
        current_month = now.month
        first_month_of_quarter = 3 * ((current_month - 1) // 3) + 1
        start_date = now.replace(
            month=first_month_of_quarter, day=1,
            hour=0, minute=0, second=0, microsecond=0
        )
        next_quarter_first_month = first_month_of_quarter + 3
        if next_quarter_first_month > 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            end_date = start_date.replace(month=next_quarter_first_month, day=1)
        return start_date, end_date

    def analyze_alpha_expressions(
        self,
        stage: str = "OS",
        alpha_type: str = "REGULAR",
    ) -> tuple[set, set, set]:
        """获取指定日期范围内的 Alpha 表达式，并提取使用的算子和数据字段。

        Args:
            stage: Alpha 阶段，默认 "OS"（已提交）
            alpha_type: Alpha 类型，默认 "REGULAR"

        Returns:
            (operators_used, operators_not_used, data_fields_used)
        """
        start_date, end_date = self.get_current_quarter_range()

        resps = self.wqbs.filter_alphas(
            others=[f"stage={stage}"],
            delay=1,
            date_submitted=FilterRange.from_str(
                f"[{start_date.isoformat()}, {end_date.isoformat()})"
            ),
            log=None,
        )

        expression_list = []
        for resp in resps:
            data = resp.json().get("results", [])
            for alpha in data:
                if alpha.get("type", "") != alpha_type:
                    continue
                expression = alpha.get("regular", {}).get("code")
                if expression:
                    expression_list.append(expression)

        operators_used = set()
        data_fields_used = set()
        for expr in expression_list:
            ops, fields = self.extract_tokens(expr)
            operators_used.update(ops)
            data_fields_used.update(fields)

        operators_not_used = self.operators - operators_used
        return operators_used, operators_not_used, data_fields_used

    def get_uncompelete_pyramids(self) -> dict:
        """获取当前季度内尚未达标的 pyramid 分类信息。

        Returns:
            {region: {delay: [category1, category2, ...]}}
        """
        start_date, end_date = self.get_current_quarter_range()
        url = (
            f"{URL_USERS_SELF_ACTIVITIES_PYRAMID_ALPHAS}"
            f"?startDate={start_date.strftime('%Y-%m-%d')}"
            f"&endDate={end_date.strftime('%Y-%m-%d')}"
        )
        resp = self.wqbs.get(url)
        pyramids = resp.json()['pyramids']
        pyramids_dict: dict = {}
        for item in pyramids:
            category = item['category']['name']
            region = item['region']
            delay = item['delay']
            alpha_count = item['alphaCount']
            if alpha_count < 3:
                pyramids_dict.setdefault(region, {})
                if delay not in pyramids_dict[region]:
                    pyramids_dict[region][delay] = []
                pyramids_dict[region][delay].append(category.replace(" ", ""))
        return pyramids_dict