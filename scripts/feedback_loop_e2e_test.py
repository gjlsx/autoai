#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud_orchestrator import db  # noqa: E402
from cloud_orchestrator.config import load_settings  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="E2E test: ai_feedback.py -> cloud orchestrator outbound loop -> Telegram")
    p.add_argument("--chat-id", default="", help="override Telegram target chat id")
    p.add_argument("--ai-target", default="codex")
    p.add_argument("--source-ai", default="codex")
    p.add_argument("--timeout-sec", type=int, default=30, help="wait timeout for delivered_tg=1")
    return p


def insert_smoke_task(settings, chat_id: str, ai_target: str) -> int:
    message = f"feedback-loop-e2e-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return db.insert_task(
        settings,
        db.TaskInsert(
            ai_target=ai_target,
            message=message,
            priority=0,
            source_channel="smoke_test",
            source_chat_id=chat_id,
            source_user_id="smoke_tester",
            idempotency_key=None,
        ),
    )


def query_feedback_row(settings, task_id: int, payload: str) -> Optional[dict]:
    conn = db.connect(settings)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, delivered_tg, delivered_tg_at, created_at "
                "FROM ai_feedback WHERE task_id=%s AND payload=%s ORDER BY id DESC LIMIT 1",
                (str(task_id), payload),
            )
            return cur.fetchone()
    finally:
        conn.close()


def run_ai_feedback(settings, task_id: int, source_ai: str, payload: str) -> None:
    env = {
        **dict(**os.environ),
        "MYSQL_HOST": settings.mysql_host,
        "MYSQL_PORT": str(settings.mysql_port),
        "MYSQL_USER": settings.mysql_user,
        "MYSQL_PASSWORD": settings.mysql_password,
        "MYSQL_DB": settings.mysql_db,
    }
    cmd = [
        sys.executable,
        "ai_feedback.py",
        "--source-ai",
        source_ai,
        "--task-id",
        str(task_id),
        "--db",
        payload,
    ]
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.stdout.strip():
        print(res.stdout.strip())
    if res.stderr.strip():
        print(res.stderr.strip())
    if res.returncode != 0:
        raise RuntimeError(f"ai_feedback.py failed with code={res.returncode}")


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings()
    chat_id = args.chat_id.strip() or settings.default_chat_id
    if args.chat_id.strip():
        settings = replace(settings, default_chat_id=args.chat_id.strip())
    if not chat_id:
        print("[feedback-loop-e2e] error: chat_id required (set --chat-id or TELEGRAM_DEFAULT_CHAT_ID)")
        return 2

    task_id = insert_smoke_task(settings, chat_id, args.ai_target)
    payload = f"feedback-loop-e2e payload {dt.datetime.now().isoformat(timespec='seconds')}"
    print(f"[feedback-loop-e2e] task_id={task_id} chat_id={chat_id}")
    run_ai_feedback(settings, task_id, args.source_ai, payload)

    deadline = time.time() + args.timeout_sec
    feedback_id = None
    while time.time() < deadline:
        row = query_feedback_row(settings, task_id, payload)
        if row:
            feedback_id = int(row["id"])
            delivered = int(row.get("delivered_tg") or 0)
            if delivered == 1:
                print(
                    f"[feedback-loop-e2e] PASS feedback_id={feedback_id} "
                    f"delivered_tg=1 delivered_tg_at={row.get('delivered_tg_at')}"
                )
                return 0
        time.sleep(1)

    if feedback_id is None:
        print("[feedback-loop-e2e] FAIL feedback row not found in ai_feedback")
    else:
        print(f"[feedback-loop-e2e] FAIL feedback_id={feedback_id} not delivered within {args.timeout_sec}s")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
