"""全局配置：所有魔法数字集中在这里，方便面试时解释"为什么是这些值"。"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # server/
ROOT_DIR = BASE_DIR.parent                             # 仓库根目录
STATIC_DIR = BASE_DIR / "app" / "static"               # 前端构建产物
DATA_DIR = BASE_DIR / "data"


def _load_env_file() -> None:
    """极简 .env 解析，避免为 Demo 引入 python-dotenv。已存在的环境变量优先。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

# ---- 大模型 ----
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 512

# 提供商：有 key 走真实模型，没 key 自动降级为本地规则引擎（保证 Demo 离线可跑）
LLM_PROVIDER = "deepseek" if LLM_API_KEY else "mock"

# ---- 业务规则（与 PRD 一一对应）----
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v2")
MAX_TEXT_LEN = 8000            # PRD 6.1 单条上限
MIN_TEXT_LEN = 10              # 低于此值提示"内容过短"
BATCH_LIMIT = 20               # PRD 6.1 批量上限
DEDUP_STRONG = "phone"         # 强重复：手机号相同
DEDUP_WINDOW_DAYS = 7          # 弱重复观察窗口
DEDUP_THRESHOLD = 0.85         # 3-gram Jaccard 阈值（PRD 6.3，需用构造样本校准）

INTENT_LEVELS = ["高", "中", "低", "无效"]
FOLLOW_STATUS = ["pending", "followed", "invalid"]
INDUSTRIES = [
    "餐饮", "零售", "教育", "美业", "房产", "汽车",
    "医疗", "金融", "本地生活", "制造", "互联网", "其他",
]

# ---- 访问控制 ----
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()   # 留空则不校验（本地演示）

DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "leads.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
