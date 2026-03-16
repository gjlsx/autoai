#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict

import redis


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Emit AI output event to Redis queue for async MySQL bridge")
    p.add_argument("--source-ai", required=True, help="ai name, e.g. codex")
    p.add_argument("--task-id", default=None, help="task id from ai_tasks")
    p.add_argument("--sessionid", default=None, help="chat session id")
    p.add_argument("--event", default="output", choices=["output", "ask", "system"], help="event type")
    p.add_argument("--text", required=True, help="message content")
    p.add_argument("--channel", default="skill", help="logical channel tag")

    p.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    p.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    p.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    p.add_argument("--redis-key", default=os.getenv("SKILL_FEEDBACK_REDIS_KEY", "ai_skill_feedback_events"))
    return p


def make_event(args: argparse.Namespace) -> Dict[str, str]:
    event = {
        "event": args.event,
        "source_ai": args.source_ai,
        "task_id": args.task_id,
        "sessionid": args.sessionid,
        "channel": args.channel,
        "payload": args.text,
        "ts": int(time.time()),
    }
    return event


def main() -> None:
    args = build_parser().parse_args()
    client = redis.Redis(
        host=args.redis_host,
        port=args.redis_port,
        db=args.redis_db,
        decode_responses=True,
    )
    event = make_event(args)
    client.lpush(args.redis_key, json.dumps(event, ensure_ascii=False))
    print(
        "[skill-emit] queued "
        + f"redis={args.redis_host}:{args.redis_port}/{args.redis_db} "
        + f"key={args.redis_key} task_id={args.task_id} source_ai={args.source_ai}"
    )


if __name__ == "__main__":
    main()

