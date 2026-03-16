from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from cloud_orchestrator import db
from cloud_orchestrator.config import Settings
from cloud_orchestrator.telegram_client import TelegramClient


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


def _extract_payload_text(raw_payload: Any) -> tuple[str, str, str]:
    payload = str(raw_payload or "")
    stripped = payload.strip()
    if not stripped:
        return "", "", ""

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return "", _strip_ansi(payload), ""
        if isinstance(data, dict):
            event = str(data.get("event") or "").strip()
            sessionid = str(data.get("sessionid") or "").strip()
            text = data.get("text")
            if text is not None:
                if isinstance(text, (dict, list)):
                    text = json.dumps(text, ensure_ascii=False)
                return event, _strip_ansi(str(text)), sessionid
    return "", _strip_ansi(payload), ""


def format_feedback(row: Dict[str, Any]) -> str:
    task_id = row.get("task_id") or "-"
    source_ai = row.get("source_ai") or "-"
    channel = row.get("channel") or "-"
    event, payload_text, payload_sessionid = _extract_payload_text(row.get("payload"))
    sessionid = str(row.get("sessionid") or payload_sessionid or "").strip()
    header = f"[{channel}] task_id={task_id} ai={source_ai}"
    if sessionid:
        header += f" sessionid={sessionid}"
    if event:
        header += f" event={event}"
    return f"{header}\n{payload_text}"


def resolve_chat_id(row: Dict[str, Any], default_chat_id: str) -> Optional[str]:
    target_chat_id = row.get("target_chat_id")
    if target_chat_id:
        return str(target_chat_id)
    if default_chat_id:
        return default_chat_id
    return None


def deliver_once(settings: Settings, tg: TelegramClient, batch_size: int = 20) -> int:
    rows = db.fetch_undelivered_feedback(settings, limit=batch_size)
    delivered = 0
    for row in rows:
        chat_id = resolve_chat_id(row, settings.default_chat_id)
        if not chat_id:
            continue
        try:
            tg.send_message(chat_id, format_feedback(row))
            db.mark_feedback_delivered(settings, int(row["id"]))
            delivered += 1
        except Exception as exc:
            db.insert_system_feedback(
                settings,
                str(row.get("task_id") or ""),
                "cloud_orchestrator",
                f"outbound delivery error feedback_id={row.get('id')} chat_id={chat_id}: {exc}",
            )
            continue
    return delivered
