#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pymysql
import redis


def validate_identifier(value: str, field: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid {field}: {value}")


@dataclass
class BridgeConfig:
    redis_host: str
    redis_port: int
    redis_db: int
    redis_key: str
    redis_retry_key: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_db: str
    mysql_table: str
    pop_timeout_sec: int
    idle_sleep_sec: float


class RedisToMysqlFeedbackBridge:
    def __init__(self, cfg: BridgeConfig):
        validate_identifier(cfg.mysql_db, "mysql_db")
        validate_identifier(cfg.mysql_table, "mysql_table")
        self.cfg = cfg
        self.redis = redis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
            decode_responses=True,
        )
        self._mysql_conn: Optional[pymysql.connections.Connection] = None

    def _mysql_connect(self) -> pymysql.connections.Connection:
        if self._mysql_conn is None:
            self._mysql_conn = pymysql.connect(
                host=self.cfg.mysql_host,
                port=self.cfg.mysql_port,
                user=self.cfg.mysql_user,
                password=self.cfg.mysql_password,
                database=self.cfg.mysql_db,
                autocommit=True,
                charset="utf8mb4",
                connect_timeout=5,
                read_timeout=15,
                write_timeout=15,
            )
            return self._mysql_conn

        try:
            self._mysql_conn.ping(reconnect=True)
        except Exception:
            try:
                self._mysql_conn.close()
            except Exception:
                pass
            self._mysql_conn = pymysql.connect(
                host=self.cfg.mysql_host,
                port=self.cfg.mysql_port,
                user=self.cfg.mysql_user,
                password=self.cfg.mysql_password,
                database=self.cfg.mysql_db,
                autocommit=True,
                charset="utf8mb4",
                connect_timeout=5,
                read_timeout=15,
                write_timeout=15,
            )
        return self._mysql_conn

    def close(self) -> None:
        if self._mysql_conn is not None:
            try:
                self._mysql_conn.close()
            except Exception:
                pass
            self._mysql_conn = None

    def _ensure_table(self) -> None:
        conn = self._mysql_connect()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.cfg.mysql_table} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id VARCHAR(128) NULL,
                    source_ai VARCHAR(64) NULL,
                    channel VARCHAR(32) NOT NULL,
                    sessionid VARCHAR(77) NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    delivered_tg TINYINT NOT NULL DEFAULT 0
                ) DEFAULT CHARSET=utf8mb4
                """
            )

    def _insert_feedback(self, event: Dict[str, Any]) -> None:
        conn = self._mysql_connect()
        channel = str(event.get("channel") or "db")
        source_ai = str(event.get("source_ai") or "unknown")
        task_id = event.get("task_id")
        sessionid = event.get("sessionid")
        payload = str(event.get("payload") or "")
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO {self.cfg.mysql_table} (task_id, source_ai, channel, payload, sessionid) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (task_id, source_ai, channel, payload, sessionid),
                )
            except pymysql.err.OperationalError as exc:
                # Backward compatibility for old table definition without sessionid.
                if exc.args and int(exc.args[0]) in {1054, 1136}:
                    cur.execute(
                        f"INSERT INTO {self.cfg.mysql_table} (task_id, source_ai, channel, payload) "
                        "VALUES (%s, %s, %s, %s)",
                        (task_id, source_ai, channel, payload),
                    )
                else:
                    raise

    def _pop_event(self) -> Optional[str]:
        item = self.redis.brpop(self.cfg.redis_key, timeout=self.cfg.pop_timeout_sec)
        if not item:
            return None
        _, raw = item
        return raw

    def process_one(self) -> bool:
        raw = self._pop_event()
        if raw is None:
            print("[redis-mysql-bridge] no event", file=sys.stderr)
            return False
        try:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("event is not object")
            self._ensure_table()
            self._insert_feedback(event)
            print(
                "[redis-mysql-bridge] inserted "
                + f"task_id={event.get('task_id')} source_ai={event.get('source_ai')} sessionid={event.get('sessionid')}"
            )
            return True
        except Exception as exc:
            retry_payload = {
                "error": str(exc),
                "raw": raw,
                "ts": int(time.time()),
            }
            self.redis.lpush(self.cfg.redis_retry_key, json.dumps(retry_payload, ensure_ascii=False))
            print(f"[redis-mysql-bridge] failed: {exc}", file=sys.stderr)
            return False

    def run_forever(self, *, max_items: int = 0) -> Tuple[int, int]:
        ok_count = 0
        fail_count = 0
        while True:
            processed = self.process_one()
            if processed:
                ok_count += 1
            else:
                fail_count += 1
                time.sleep(self.cfg.idle_sleep_sec)

            if max_items > 0 and (ok_count + fail_count) >= max_items:
                break
        return ok_count, fail_count


def _strip_wrapping_quotes(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
        return value[1:-1]
    return value


def _parse_dotenv_mysql(dotenv_path: Path) -> Dict[str, str]:
    if not dotenv_path.exists():
        return {}
    text = dotenv_path.read_text(encoding="utf-8", errors="replace")

    def pick(name: str) -> str:
        m = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", text)
        if not m:
            return ""
        return _strip_wrapping_quotes(m.group(1))

    host = pick("MYSQL_HOST")
    port = pick("MYSQL_PORT")
    user = pick("MYSQL_USER")
    password = pick("MYSQL_PASSWORD")
    db = pick("MYSQL_DB")

    # Legacy note line fallback, same behavior as one_click parser.
    if not host or not port:
        m_host = re.search(r"(?m)^\s*([A-Za-z0-9\.-]+)\s+(\d{2,5})\s*$", text)
        if m_host:
            host = host or m_host.group(1).strip()
            port = port or m_host.group(2).strip()

    if not user or not password:
        m_user = re.search(r"(?mi)^\s*([A-Za-z0-9_]+)\s+[^\r\n]*?pwd:\s*([^\s]+)\s*$", text)
        if m_user:
            user = user or m_user.group(1).strip()
            password = password or m_user.group(2).strip()

    if not db and user:
        m_db = re.match(r"^(.*)wr$", user)
        if m_db and m_db.group(1):
            db = m_db.group(1)

    out = {
        "MYSQL_HOST": host,
        "MYSQL_PORT": port,
        "MYSQL_USER": user,
        "MYSQL_PASSWORD": password,
        "MYSQL_DB": db,
    }
    if all(out.values()):
        return out
    return {}


def apply_dotenv_mysql_defaults(args: argparse.Namespace, dotenv_path: Path = Path(".env")) -> None:
    # If caller already provided non-default mysql auth, do not override.
    user_default = args.mysql_user == "root"
    password_default = args.mysql_password == ""
    host_default = args.mysql_host == "127.0.0.1"
    db_default = args.mysql_db == "autoai"
    if not (user_default and password_default):
        return

    cfg = {}
    try:
        # Keep parser behavior identical to existing one_click path.
        from scripts.one_click import parse_project_env  # pylint: disable=import-outside-toplevel

        cfg = parse_project_env(dotenv_path)
    except Exception:
        cfg = _parse_dotenv_mysql(dotenv_path)
    if not cfg:
        return

    args.mysql_host = cfg["MYSQL_HOST"] or args.mysql_host
    args.mysql_port = int(cfg["MYSQL_PORT"] or args.mysql_port)
    args.mysql_user = cfg["MYSQL_USER"] or args.mysql_user
    args.mysql_password = cfg["MYSQL_PASSWORD"] or args.mysql_password
    if db_default or cfg["MYSQL_DB"]:
        args.mysql_db = cfg["MYSQL_DB"] or args.mysql_db
    if host_default or cfg["MYSQL_HOST"]:
        args.mysql_host = cfg["MYSQL_HOST"] or args.mysql_host


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bridge events from Redis list to MySQL ai_feedback")
    p.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    p.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    p.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    p.add_argument("--redis-key", default=os.getenv("SKILL_FEEDBACK_REDIS_KEY", "ai_skill_feedback_events"))
    p.add_argument("--redis-retry-key", default=os.getenv("SKILL_FEEDBACK_RETRY_KEY", "ai_skill_feedback_retry"))
    p.add_argument("--pop-timeout-sec", type=int, default=2)
    p.add_argument("--idle-sleep-sec", type=float, default=0.3)

    p.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    p.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    p.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    p.add_argument("--mysql-db", default=os.getenv("MYSQL_DB", "autoai"))
    p.add_argument("--mysql-table", default="ai_feedback")

    p.add_argument("--once", action="store_true", help="process one message then exit")
    p.add_argument("--max-items", type=int, default=0, help="for bounded run in tests")
    return p


def main() -> None:
    args = build_parser().parse_args()
    apply_dotenv_mysql_defaults(args)
    cfg = BridgeConfig(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=args.redis_db,
        redis_key=args.redis_key,
        redis_retry_key=args.redis_retry_key,
        mysql_host=args.mysql_host,
        mysql_port=args.mysql_port,
        mysql_user=args.mysql_user,
        mysql_password=args.mysql_password,
        mysql_db=args.mysql_db,
        mysql_table=args.mysql_table,
        pop_timeout_sec=args.pop_timeout_sec,
        idle_sleep_sec=args.idle_sleep_sec,
    )
    bridge = RedisToMysqlFeedbackBridge(cfg)
    try:
        if args.once:
            ok = bridge.process_one()
            print(f"[redis-mysql-bridge] once processed={ok}")
            return
        ok_count, fail_count = bridge.run_forever(max_items=args.max_items)
        print(f"[redis-mysql-bridge] done ok={ok_count} fail={fail_count}")
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
