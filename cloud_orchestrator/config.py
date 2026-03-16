from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_db: str
    api_host: str
    api_port: int
    api_key: str
    default_chat_id: str
    inbound_poll_interval_sec: float
    outbound_poll_interval_sec: float
    telegram_get_updates_timeout_sec: int
    allowed_ai_targets: Tuple[str, ...]


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"missing required env: {name}")
    return value


def _split_targets(raw: str) -> Tuple[str, ...]:
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not items:
        return ("codex", "claude", "gemini")
    return tuple(items)


def _parse_legacy_notes(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    found: Dict[str, str] = {}

    token = re.search(r"(\d{6,}:[A-Za-z0-9_-]{20,})", content)
    if token:
        found["TELEGRAM_BOT_TOKEN"] = token.group(1)

    mysql_line = re.search(r"([A-Za-z0-9.-]+)\s+(\d{2,5})", content)
    if mysql_line:
        found["MYSQL_HOST"] = mysql_line.group(1)
        found["MYSQL_PORT"] = mysql_line.group(2)

    user_pwd = re.search(r"([A-Za-z0-9_]+)\s+数据库\s*pwd:\s*([^\s]+)", content)
    if user_pwd:
        mysql_user = user_pwd.group(1)
        found["MYSQL_USER"] = mysql_user
        found["MYSQL_PASSWORD"] = user_pwd.group(2)

    if "MYSQL_DB" not in found:
        mysql_user = found.get("MYSQL_USER", "")
        m_db = re.match(r"^(.*)wr$", mysql_user)
        if m_db and m_db.group(1):
            found["MYSQL_DB"] = m_db.group(1)
        else:
            found["MYSQL_DB"] = "autoai"

    return found


def _apply_fallbacks(values: Dict[str, str]) -> None:
    for key, value in values.items():
        if not os.getenv(key):
            os.environ[key] = value


def _looks_like_dotenv(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", stripped):
                return True
            return False
    except OSError:
        return False
    return False


def load_settings(env_file: str | None = None, legacy_fallback: bool = True) -> Settings:
    if env_file:
        legacy_path = Path(env_file)
        if _looks_like_dotenv(legacy_path):
            load_dotenv(env_file, override=False)
    else:
        default_env = Path.cwd() / ".env"
        if _looks_like_dotenv(default_env):
            load_dotenv(default_env, override=False)
        legacy_path = default_env

    if legacy_fallback:
        _apply_fallbacks(_parse_legacy_notes(legacy_path))

    return Settings(
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        mysql_host=_required("MYSQL_HOST"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=_required("MYSQL_USER"),
        mysql_password=_required("MYSQL_PASSWORD"),
        mysql_db=_required("MYSQL_DB"),
        api_host=os.getenv("ORCH_API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("ORCH_API_PORT", "18080")),
        api_key=os.getenv("ORCH_API_KEY", "").strip(),
        default_chat_id=os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "").strip(),
        inbound_poll_interval_sec=float(os.getenv("INBOUND_POLL_INTERVAL_SEC", "1.0")),
        outbound_poll_interval_sec=float(os.getenv("OUTBOUND_POLL_INTERVAL_SEC", "2.0")),
        telegram_get_updates_timeout_sec=int(os.getenv("TELEGRAM_GET_UPDATES_TIMEOUT_SEC", "20")),
        allowed_ai_targets=_split_targets(os.getenv("ALLOWED_AI_TARGETS", "codex,claude,gemini")),
    )
