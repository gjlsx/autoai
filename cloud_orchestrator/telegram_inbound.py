from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from cloud_orchestrator import db
from cloud_orchestrator.config import Settings
from cloud_orchestrator.telegram_client import TelegramClient


@dataclass(frozen=True)
class ParsedTask:
    target: str
    message: str


def parse_command(text: str, allowed_targets: Sequence[str] = ("codex", "claude", "gemini")) -> Tuple[str, str]:
    cleaned = text.strip()
    allowed = {item.lower() for item in allowed_targets}

    slash_match = re.match(r"^/to(?:@\w+)?\s+([a-zA-Z0-9_-]+)\s+(.+)$", cleaned)
    if slash_match:
        target = slash_match.group(1).strip().lower()
        message = slash_match.group(2).strip()
        if target not in allowed:
            raise ValueError(f"unsupported target: {target}")
        if not message:
            raise ValueError("empty message")
        return target, message

    if ":" in cleaned:
        target, message = cleaned.split(":", 1)
        target = target.strip().lower()
        message = message.strip()
        if target not in allowed:
            raise ValueError(f"unsupported target: {target}")
        if not message:
            raise ValueError("empty message")
        return target, message

    raise ValueError("unsupported command format")


def is_status_command(text: str) -> bool:
    return bool(re.match(r"^/status(?:@\w+)?\s+\d+\s*$", text.strip()))


def extract_status_task_id(text: str) -> int:
    match = re.match(r"^/status(?:@\w+)?\s+(\d+)\s*$", text.strip())
    if not match:
        raise ValueError("invalid /status format")
    return int(match.group(1))


def help_text() -> str:
    return (
        "Usage:\n"
        "/to <claude|gemini|codex> <message>\n"
        "/status <task_id>\n"
        "/myid\n"
        "You can also use: codex:your message"
    )


def process_message(
    settings: Settings,
    tg: TelegramClient,
    chat_id: str,
    user_id: str,
    text: str,
    update_id: Optional[int] = None,
) -> Optional[int]:
    normalized = text.strip()
    if not normalized:
        return None

    if normalized.startswith("/start") or normalized.startswith("/help"):
        tg.send_message(chat_id, help_text())
        return None

    if normalized.startswith("/myid"):
        tg.send_message(chat_id, f"chat_id={chat_id}")
        return None

    if is_status_command(normalized):
        task_id = extract_status_task_id(normalized)
        row = db.get_task_status(settings, task_id)
        if row is None:
            tg.send_message(chat_id, f"task_id={task_id} not found")
            return None
        tg.send_message(
            chat_id,
            f"task_id={row['id']} target={row['ai_target']} status={row['status']} error={row['last_error'] or '-'}",
        )
        return None

    try:
        target, message = parse_command(normalized, settings.allowed_ai_targets)
    except ValueError:
        tg.send_message(chat_id, "invalid command.\n" + help_text())
        return None

    dedupe = None
    if update_id is not None:
        dedupe = f"tg:{chat_id}:{update_id}"
    sessionid = f"tg:{chat_id}:{target}"[:77]
    task_id = db.insert_task_from_telegram(
        settings=settings,
        ai_target=target,
        message=message,
        chat_id=str(chat_id),
        user_id=str(user_id),
        idempotency_key=dedupe,
        sessionid=sessionid,
    )
    tg.send_message(chat_id, f"accepted task_id={task_id}, target={target}")
    return task_id
