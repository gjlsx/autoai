import argparse
import json
import os
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import pymysql
import redis


DEFAULT_ROUTING = {"claude": 9001, "gemini": 9002, "codex": 9003}


@dataclass
class Task:
    source: str
    target: str
    message: str
    task_id: Optional[str] = None
    sessionid: Optional[str] = None
    meta: Dict[str, str] = field(default_factory=dict)


class Dispatcher:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.routing = self._parse_routing(args.routing)
        self.task_queue: "queue.Queue[Task]" = queue.Queue()
        self.shutdown = threading.Event()
        self.mysql_local = threading.local()

        self.redis_client = redis.Redis(
            host=args.redis_host,
            port=args.redis_port,
            db=args.redis_db,
            decode_responses=True,
        )
        self._validate_identifier(self.args.mysql_db, "mysql_db")

    def recover_stale_dispatching(self) -> None:
        if not self.args.enable_mysql:
            return
        sql = (
            "UPDATE ai_tasks "
            "SET status='pending', updated_at=NOW(), last_error=COALESCE(last_error, 'recovered stale dispatching') "
            "WHERE status='dispatching' "
            "AND TIMESTAMPDIFF(SECOND, COALESCE(updated_at, created_at), NOW()) > %s"
        )
        conn = self._get_mysql_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (self.args.recover_dispatching_sec,))
            if cur.rowcount > 0:
                print(f"[dispatcher] recovered stale dispatching tasks: {cur.rowcount}")

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]+", value):
            raise ValueError(f"invalid {name}: {value}")

    def _connect_mysql(self):
        try:
            return pymysql.connect(
                host=self.args.mysql_host,
                port=self.args.mysql_port,
                user=self.args.mysql_user,
                password=self.args.mysql_password,
                database=self.args.mysql_db,
                autocommit=True,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1049:
                conn = pymysql.connect(
                    host=self.args.mysql_host,
                    port=self.args.mysql_port,
                    user=self.args.mysql_user,
                    password=self.args.mysql_password,
                    autocommit=True,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"CREATE DATABASE IF NOT EXISTS `{self.args.mysql_db}` "
                            "DEFAULT CHARACTER SET utf8mb4"
                        )
                finally:
                    conn.close()
                return pymysql.connect(
                    host=self.args.mysql_host,
                    port=self.args.mysql_port,
                    user=self.args.mysql_user,
                    password=self.args.mysql_password,
                    database=self.args.mysql_db,
                    autocommit=True,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                )
            raise

    def _get_mysql_conn(self):
        conn = getattr(self.mysql_local, "conn", None)
        if conn is None:
            conn = self._connect_mysql()
            self.mysql_local.conn = conn
            return conn
        try:
            conn.ping(reconnect=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = self._connect_mysql()
            self.mysql_local.conn = conn
        return conn

    def _reset_mysql_conn(self) -> None:
        conn = getattr(self.mysql_local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if hasattr(self.mysql_local, "conn"):
            delattr(self.mysql_local, "conn")

    @staticmethod
    def _parse_routing(raw: str) -> Dict[str, int]:
        if not raw:
            return DEFAULT_ROUTING.copy()
        routing = {}
        for item in raw.split(","):
            if "=" not in item:
                continue
            name, port = item.split("=", 1)
            name = name.strip().lower()
            routing[name] = int(port.strip())
        return routing or DEFAULT_ROUTING.copy()

    @staticmethod
    def _parse_payload(raw: str, source: str) -> Optional[Task]:
        payload = raw.strip()
        if not payload:
            return None
        if payload.startswith("{"):
            data = json.loads(payload)
            target = str(data.get("target", "")).strip().lower()
            message = str(data.get("message") or data.get("prompt") or "").strip()
            task_id = data.get("task_id") or data.get("id")
            sessionid = data.get("sessionid")
            if not target or not message:
                return None
            return Task(
                source=source,
                target=target,
                message=message,
                task_id=str(task_id) if task_id else None,
                sessionid=str(sessionid).strip() if sessionid not in {None, ""} else None,
                meta={
                    k: str(v)
                    for k, v in data.items()
                    if k not in {"target", "message", "prompt", "task_id", "id", "sessionid"}
                },
            )

        if ":" in payload:
            target, message = payload.split(":", 1)
            target = target.strip().lower()
            message = message.strip()
            if target and message:
                return Task(source=source, target=target, message=message)
        return None

    def init_schema(self) -> None:
        conn = self._get_mysql_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_tasks (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    ai_target VARCHAR(64) NOT NULL,
                    message TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    priority INT NOT NULL DEFAULT 0,
                    sessionid VARCHAR(77) NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL,
                    dispatched_at DATETIME NULL,
                    last_error TEXT NULL
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_feedback (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id VARCHAR(128) NULL,
                    source_ai VARCHAR(64) NULL,
                    channel VARCHAR(32) NOT NULL,
                    sessionid VARCHAR(77) NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) DEFAULT CHARSET=utf8mb4
                """
            )
        print("[dispatcher] schema initialized: ai_tasks, ai_feedback")

    def send_to_window(self, task: Task) -> bool:
        port = self.routing.get(task.target)
        if not port:
            print(f"[dispatcher] unknown target '{task.target}', skip")
            return False

        envelope = {
            "task_id": task.task_id,
            "target": task.target,
            "source": task.source,
            "message": task.message,
            "sessionid": task.sessionid,
            "meta": task.meta,
            "ts": int(time.time()),
        }
        source_chat_id = task.meta.get("source_chat_id")
        source_user_id = task.meta.get("source_user_id")
        if source_chat_id:
            envelope["source_chat_id"] = source_chat_id
        if source_user_id:
            envelope["source_user_id"] = source_user_id
        payload = json.dumps(envelope, ensure_ascii=False)

        last_error = None
        for _ in range(self.args.socket_retries + 1):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=self.args.socket_timeout) as conn:
                    conn.sendall(payload.encode("utf-8"))
                    conn.shutdown(socket.SHUT_WR)
                    ack = conn.recv(1024).decode("utf-8", errors="replace").strip()
                    if ack and not ack.startswith("OK"):
                        raise OSError(f"worker rejected payload: {ack}")
                return True
            except OSError as exc:
                last_error = str(exc)
                time.sleep(self.args.retry_backoff_sec)

        print(f"[dispatcher] failed to connect target={task.target} port={port}: {last_error}")
        return False

    def listen_redis(self) -> None:
        while not self.shutdown.is_set():
            try:
                item = self.redis_client.brpop(self.args.redis_queue, timeout=2)
                if not item:
                    continue
                _, raw = item
                task = self._parse_payload(raw, source="redis")
                if task:
                    self.task_queue.put(task)
                else:
                    print(f"[dispatcher] invalid redis payload: {raw}")
            except Exception as exc:
                print(f"[dispatcher] redis listener error: {exc}")
                time.sleep(1)

    def listen_mysql(self) -> None:
        query = (
            "SELECT id, ai_target, message, sessionid, source_chat_id, source_user_id FROM ai_tasks "
            "WHERE status='pending' ORDER BY priority DESC, id ASC LIMIT %s"
        )
        query_legacy = (
            "SELECT id, ai_target, message FROM ai_tasks "
            "WHERE status='pending' ORDER BY priority DESC, id ASC LIMIT %s"
        )
        lock_query = "UPDATE ai_tasks SET status='dispatching', updated_at=NOW() WHERE id=%s AND status='pending'"

        while not self.shutdown.is_set():
            try:
                conn = self._get_mysql_conn()
                with conn.cursor() as cur:
                    try:
                        cur.execute(query, (self.args.mysql_batch_size,))
                        rows = cur.fetchall()
                    except pymysql.err.OperationalError as exc:
                        if exc.args and exc.args[0] == 1054:
                            cur.execute(query_legacy, (self.args.mysql_batch_size,))
                            rows = cur.fetchall()
                            for row in rows:
                                row["sessionid"] = None
                                row["source_chat_id"] = None
                                row["source_user_id"] = None
                        else:
                            raise
                for row in rows:
                    with conn.cursor() as cur:
                        cur.execute(lock_query, (row["id"],))
                        if cur.rowcount != 1:
                            continue
                    task = Task(
                        source="mysql",
                        target=str(row["ai_target"]).strip().lower(),
                        message=str(row["message"]).strip(),
                        task_id=str(row["id"]),
                        sessionid=(str(row.get("sessionid")).strip() if row.get("sessionid") else None),
                        meta={
                            "source_chat_id": str(row.get("source_chat_id") or ""),
                            "source_user_id": str(row.get("source_user_id") or ""),
                        },
                    )
                    self.task_queue.put(task)
                time.sleep(self.args.mysql_poll_interval)
            except Exception as exc:
                print(f"[dispatcher] mysql listener error: {exc}")
                self._reset_mysql_conn()
                time.sleep(1)

    def listen_user(self) -> None:
        while not self.shutdown.is_set():
            try:
                raw = input("input task (target:message or JSON)> ").strip()
                if raw.lower() in {"quit", "exit"}:
                    self.shutdown.set()
                    return
                task = self._parse_payload(raw, source="user")
                if task:
                    self.task_queue.put(task)
                else:
                    print("[dispatcher] invalid input format, e.g. codex:analyze logs")
            except EOFError:
                self.shutdown.set()
                return
            except KeyboardInterrupt:
                self.shutdown.set()
                return
            except Exception as exc:
                print(f"[dispatcher] user listener error: {exc}")

    def wait_forever(self) -> None:
        print("[dispatcher] no-user-input mode enabled, listening mysql/redis only (Ctrl+C to stop)")
        while not self.shutdown.is_set():
            time.sleep(0.5)

    def _mark_mysql_result(self, task: Task, ok: bool, err: Optional[str] = None) -> None:
        if task.source != "mysql" or not task.task_id:
            return
        if ok:
            sql = (
                "UPDATE ai_tasks SET status='dispatched', dispatched_at=NOW(), "
                "updated_at=NOW(), last_error=NULL WHERE id=%s"
            )
            args = (task.task_id,)
        else:
            sql = "UPDATE ai_tasks SET status='failed', updated_at=NOW(), last_error=%s WHERE id=%s"
            args = (err or "dispatch failed", task.task_id)
        conn = self._get_mysql_conn()
        with conn.cursor() as cur:
            cur.execute(sql, args)

    def dispatch_loop(self) -> None:
        while not self.shutdown.is_set() or not self.task_queue.empty():
            try:
                task = self.task_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                ok = self.send_to_window(task)
                try:
                    self._mark_mysql_result(task, ok, None if ok else "socket send failed")
                except Exception as exc:
                    print(f"[dispatcher] mysql mark result error: {exc}")
                    self._reset_mysql_conn()
                print(
                    f"[dispatcher] source={task.source} target={task.target} "
                    f"task_id={task.task_id or '-'} status={'ok' if ok else 'failed'}"
                )
            finally:
                self.task_queue.task_done()

    def run(self) -> None:
        if self.args.init_schema:
            self.init_schema()
        self.recover_stale_dispatching()

        threads = []
        if self.args.enable_redis:
            threads.append(threading.Thread(target=self.listen_redis, daemon=True))
        if self.args.enable_mysql:
            threads.append(threading.Thread(target=self.listen_mysql, daemon=True))
        threads.append(threading.Thread(target=self.dispatch_loop, daemon=True))
        for t in threads:
            t.start()

        try:
            if self.args.no_user_input:
                self.wait_forever()
            else:
                self.listen_user()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown.set()
            self.task_queue.join()
            self._reset_mysql_conn()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Matrix dispatcher")
    parser.add_argument("--routing", default="claude=9001,gemini=9002,codex=9003")

    parser.add_argument("--enable-redis", dest="enable_redis", action="store_true", default=True)
    parser.add_argument("--disable-redis", dest="enable_redis", action="store_false")
    parser.add_argument("--enable-mysql", dest="enable_mysql", action="store_true", default=True)
    parser.add_argument("--disable-mysql", dest="enable_mysql", action="store_false")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-db", type=int, default=0)
    parser.add_argument("--redis-queue", default="ai_task_queue")

    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", "gj"))
    parser.add_argument("--mysql-db", default=os.getenv("MYSQL_DB", "autoai"))
    parser.add_argument("--mysql-poll-interval", type=float, default=1.0)
    parser.add_argument("--mysql-batch-size", type=int, default=20)

    parser.add_argument("--socket-timeout", type=float, default=3.0)
    parser.add_argument("--socket-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-sec", type=float, default=0.5)
    parser.add_argument("--init-schema", action="store_true")
    parser.add_argument(
        "--recover-dispatching-sec",
        type=int,
        default=60,
        help="Recover mysql tasks stuck in dispatching longer than this seconds",
    )
    parser.add_argument(
        "--no-user-input",
        action="store_true",
        help="Do not read terminal input; dispatch only from mysql/redis listeners",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatcher = Dispatcher(args)
    dispatcher.run()


if __name__ == "__main__":
    main()
