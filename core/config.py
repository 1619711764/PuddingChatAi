# 🍮Chat v2 — 核心配置（本地方案）
# SQLite + JWT，零外部依赖

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = PROJECT_ROOT / "static"


@dataclass
class LLMConfig:
    provider: str = os.getenv("LLM_PROVIDER", "openai")
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    api_base: str = os.getenv("OPENAI_API_BASE", "")
    model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    timeout: int = int(os.getenv("LLM_TIMEOUT", "60"))


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    max_history_messages: int = 20
    conversation_ttl_hours: int = 720
    db_path: str = str(DATA_DIR / "conversations.db")
    static_dir: str = str(STATIC_DIR)
    memory_extract_threshold: int = 5
    jwt_secret: str = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
    jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "168"))  # 7 天
