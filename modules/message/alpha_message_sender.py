import logging

import requests

from wqbkit.app.config import config

logger = logging.getLogger(__name__)

DEFAULT_GROUP_NAME = "Default"
DEFAULT_ICON_URL = "https://www.worldquant.com/favicon.ico"
DEFAULT_LEVEL = "active"
DEFAULT_BADGE = 1
DEFAULT_SOUND = "minuet.caf"
REQUEST_TIMEOUT_SECONDS = 10


def sc_send(title: str, content: str = "", groupName: str = DEFAULT_GROUP_NAME) -> None:
    """
    发送消息到 Bark App (支持 iOS 推送)
    
    该函数会自动处理特殊字符编码，并支持长文本发送。
    优先使用 POST 方法，以支持更丰富的内容格式。

    Args:
        title: 消息标题
        content: 消息内容
        groupName: 消息分组名称，用于在通知中心归类
    """
    bark_key = config.BARK_KEY
    if not bark_key:
        logger.warning("未配置 BARK_KEY，跳过消息发送")
        return

    base_url = config.BARK_BASE_URL.rstrip("/")
    push_url = f"{base_url}/push"

    payload = {
        "device_key": bark_key,
        "title": title,
        "body": content,
        "group": groupName,
        "icon": DEFAULT_ICON_URL,
        "level": DEFAULT_LEVEL,
        "badge": DEFAULT_BADGE,
        "sound": DEFAULT_SOUND,
    }

    try:
        response = requests.post(push_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        
        result = response.json()
        if result.get("code") != 200:
            logger.error(f"Bark API 返回错误: {result}")
        else:
            logger.debug(f"Bark 消息发送成功: {title}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"发送 Bark 消息网络请求失败: {e}")
    except Exception as e:
        logger.error(f"发送 Bark 消息发生未知错误: {e}")
