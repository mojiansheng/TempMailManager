"""全局配置与常量。"""

import os
import sys
from pathlib import Path

APP_NAME = "TempMail Manager"


def _base_dir() -> Path:
    """打包后以 exe 所在目录为基准，源码运行以项目根目录为基准。"""
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()

# 静态资源目录（模板/前端）
RESOURCE_DIR = Path(__file__).resolve().parent

# 数据目录：可用环境变量覆盖，默认 exe 同级 data/
DATA_DIR = Path(os.environ.get("TEMPMAIL_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "tempmail.db"

HOST = os.environ.get("TEMPMAIL_HOST", "127.0.0.1")
PORT = int(os.environ.get("TEMPMAIL_PORT", "8720"))
DEBUG = os.environ.get("TEMPMAIL_DEBUG", "0") == "1"

# ---------------- 目标站点 ----------------
SITE_BASE = "https://onetimeemail.com"
# 站点语言前缀，影响返回的措辞，不影响数据
SITE_LANG = "zh-hans"
SITE_PREFIX = f"/{SITE_LANG}"

# 有效期白名单（站点仅接受这些值，顺序即下拉顺序）
LIFETIME_OPTIONS = ["10m", "30m", "1h", "3h", "6h", "24h", "3d", "7d", "15d", "30d"]
DEFAULT_LIFETIME = "30d"
MAX_LIFETIME = "30d"

# 有效期中文名称（前端下拉展示用）
LIFETIME_LABELS = {
    "10m": "10 分钟",
    "30m": "30 分钟",
    "1h": "1 小时",
    "3h": "3 小时",
    "6h": "6 小时",
    "24h": "24 小时",
    "3d": "3 天",
    "7d": "7 天",
    "15d": "15 天",
    "30d": "30 天",
}


def lifetime_choices() -> list:
    """[(value, label)]，供模板渲染下拉。"""
    return [(v, LIFETIME_LABELS.get(v, v)) for v in LIFETIME_OPTIONS]

# 自动续期间隔（秒）。站点最长 30 天，每天续一次即可。
RENEW_INTERVAL_SECONDS = 24 * 3600
# 后台巡检轮询间隔（秒）
SCHEDULER_TICK_SECONDS = int(os.environ.get("TEMPMAIL_TICK", "300"))

HTTP_TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
