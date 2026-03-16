#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import replace
from pathlib import Path
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud_orchestrator import db
from cloud_orchestrator.config import load_settings
from cloud_orchestrator.telegram_client import TelegramClient
from cloud_orchestrator.telegram_outbound import deliver_once


def insert_smoke_feedback(
    settings,
    *,
    chat_id: str,
    ai_target: str,
    source_ai: str,
    payload: str,
) -> tuple[int, int]:
    task_message = f"feedback-smoke-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    task_id = db.insert_task(
        settings,
        db.TaskInsert(
            ai_target=ai_target,
            message=task_message,
            priority=0,
            source_channel="smoke_test",
            source_chat_id=chat_id,
            source_user_id="smoke_tester",
            idempotency_key=None,
        ),
    )

    conn = db.connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_feedback (task_id, source_ai, channel, payload) VALUES (%s, %s, %s, %s)",
                (str(task_id), source_ai, "db", payload),
            )
            feedback_id = int(cur.lastrowid)
    finally:
        conn.close()
    return task_id, feedback_id


def query_feedback_delivered(settings, feedback_id: int) -> Optional[int]:
    conn = db.connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT delivered_tg FROM ai_feedback WHERE id=%s", (feedback_id,))
            row = cur.fetchone()
            if not row:
                return None
            return int(row.get("delivered_tg") or 0)
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Smoke test: ai_feedback -> Telegram delivery")
    p.add_argument("--chat-id", default="", help="override Telegram target chat id")
    p.add_argument("--ai-target", default="codex", help="task ai_target for synthetic smoke row")
    p.add_argument("--source-ai", default="codex", help="source_ai written into ai_feedback")
    p.add_argument("--payload", default="feedback smoke from script", help="feedback payload")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument(
        "--inject",
        action="store_true",
        help="inject one synthetic task+feedback row before running deliver_once",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings()
    chat_id = args.chat_id.strip() or settings.default_chat_id
    if args.chat_id.strip():
        settings = replace(settings, default_chat_id=args.chat_id.strip())

    feedback_id: Optional[int] = None
    if args.inject:
        if not chat_id:
            print("[feedback-flow-test] error: chat_id required for --inject (pass --chat-id or set TELEGRAM_DEFAULT_CHAT_ID)")
            return 2
        task_id, feedback_id = insert_smoke_feedback(
            settings,
            chat_id=chat_id,
            ai_target=args.ai_target,
            source_ai=args.source_ai,
            payload=args.payload,
        )
        print(f"[feedback-flow-test] injected task_id={task_id}, feedback_id={feedback_id}, chat_id={chat_id}")

    tg = TelegramClient(settings.telegram_bot_token)
    delivered = deliver_once(settings, tg, batch_size=args.batch_size)
    print(f"[feedback-flow-test] deliver_once delivered={delivered}")

    if feedback_id is None:
        print("[feedback-flow-test] no injected row to assert, done")
        return 0

    delivered_flag = query_feedback_delivered(settings, feedback_id)
    if delivered_flag == 1:
        print(f"[feedback-flow-test] PASS feedback_id={feedback_id} delivered_tg=1")
        return 0

    print(f"[feedback-flow-test] FAIL feedback_id={feedback_id} delivered_tg={delivered_flag}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
