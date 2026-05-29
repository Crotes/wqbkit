"""WorldQuant Brain Alpha Research Toolkit"""

import os
from dotenv import load_dotenv

# 显式加载项目根目录的 .env（适用于 editable install 模式）
# load_dotenv 默认 override=False，不会覆盖已存在的环境变量
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

__version__ = "0.1.0"
