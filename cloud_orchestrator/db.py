from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pymysql

from cloud_orchestrator.config import Settings


class SQL:
    INSERT_TASK = (
        "INSERT INTO ai_tasks "
        "(ai_target, message, status, priority, source_channel, source_chat_id, source_user_id, idempotency_key, sessionid, updated_at) "
        "VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s, %s, NOW())"
    )
    INSERT_TASK_MINIMAL = (
        "INSERT INTO ai_tasks (ai_target, message, status, priority, sessionid, updated_at) "
        "VALUES (%s, %s, 'pending', %s, %s, NOW())"
    )
    SELECT_TASK_BY_ID = (
        "SELECT id, ai_target, message, status, priority, sessionid, created_at, updated_at, dispatched_at, last_error "
        "FROM ai_tasks WHERE id=%s"
    )
    SELECT_TASK_ID_BY_IDEMPOTENCY = "SELECT id FROM ai_tasks WHERE idempotency_key=%s ORDER BY id DESC LIMIT 1"
    SELECT_FEEDBACK_BY_TASK_ID = (
        "SELECT id, task_id, source_ai, channel, payload, sessionid, created_at, delivered_tg, delivered_tg_at "
        "FROM ai_feedback WHERE task_id=%s ORDER BY id ASC LIMIT %s"
    )
    SELECT_UNDELIVERED_FEEDBACK = (
        "SELECT f.id, f.task_id, f.source_ai, f.channel, f.payload, f.sessionid, f.created_at, "
        "t.source_chat_id AS target_chat_id "
        "FROM ai_feedback f "
        "LEFT JOIN ai_tasks t ON CAST(t.id AS CHAR) = f.task_id "
        "WHERE f.delivered_tg = 0 "
        "ORDER BY f.id ASC "
        "LIMIT %s"
    )
    MARK_FEEDBACK_DELIVERED = "UPDATE ai_feedback SET delivered_tg=1, delivered_tg_at=NOW() WHERE id=%s"
    INSERT_FEEDBACK = (
        "INSERT INTO ai_feedback (task_id, source_ai, channel, payload, sessionid) VALUES (%s, %s, %s, %s, %s)"
    )


@dataclass(frozen=True)
class TaskInsert:
    ai_target: str
    message: str
    priority: int = 0
    source_channel: Optional[str] = None
    source_chat_id: Optional[str] = None
    source_user_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    sessionid: Optional[str] = None


_CONN_LOCK = threading.RLock()
_CONN: Any = None
_CONN_KEY: tuple[str, int, str, str, str] | None = None
_RECONNECT_ERRNOS = {2003, 2006, 2013, 2055}


def _validate_identifier(value: str, field: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid {field}: {value}")


def _conn_key(settings: Settings) -> tuple[str, int, str, str, str]:
    return (
        settings.mysql_host,
        int(settings.mysql_port),
        settings.mysql_user,
        settings.mysql_password,
        settings.mysql_db,
    )


def _new_connection(settings: Settings):
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
    )


def _close_conn_silent(conn: Any) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def reset_connection_cache() -> None:
    global _CONN, _CONN_KEY
    with _CONN_LOCK:
        _close_conn_silent(_CONN)
        _CONN = None
        _CONN_KEY = None


def _is_reconnect_error(exc: Exception) -> bool:
    if not isinstance(exc, pymysql.err.OperationalError):
        return False
    if not exc.args:
        return False
    try:
        errno = int(exc.args[0])
    except Exception:
        return False
    return errno in _RECONNECT_ERRNOS


def connect(settings: Settings):
    global _CONN, _CONN_KEY
    _validate_identifier(settings.mysql_db, "mysql_db")
    wanted = _conn_key(settings)
    with _CONN_LOCK:
        if _CONN is not None and _CONN_KEY != wanted:
            _close_conn_silent(_CONN)
            _CONN = None
            _CONN_KEY = None

        if _CONN is None:
            _CONN = _new_connection(settings)
            _CONN_KEY = wanted
            return _CONN

        try:
            _CONN.ping(reconnect=True)
        except Exception:
            _close_conn_silent(_CONN)
            _CONN = _new_connection(settings)
            _CONN_KEY = wanted
        return _CONN


def _run_with_cursor(settings: Settings, operation: Callable[[Any], Any]) -> Any:
    with _CONN_LOCK:
        for attempt in range(2):
            conn = connect(settings)
            try:
                with conn.cursor() as cur:
                    return operation(cur)
            except Exception as exc:
                if attempt == 0 and _is_reconnect_error(exc):
                    _close_conn_silent(conn)
                    # force reconnect on next loop
                    global _CONN, _CONN_KEY
                    _CONN = None
                    _CONN_KEY = None
                    continue
                raise


def insert_task(settings: Settings, payload: TaskInsert) -> int:
    def op(cur: Any) -> int:
        try:
            cur.execute(
                SQL.INSERT_TASK,
                (
                    payload.ai_target,
                    payload.message,
                    payload.priority,
                    payload.source_channel,
                    payload.source_chat_id,
                    payload.source_user_id,
                    payload.idempotency_key,
                    payload.sessionid,
                ),
            )
        except pymysql.err.IntegrityError as exc:
            # Idempotent telegram/webhook inserts: return existing row id instead of failing caller.
            errno = None
            if exc.args:
                try:
                    errno = int(exc.args[0])
                except Exception:
                    errno = None
            if payload.idempotency_key and errno == 1062:
                cur.execute(SQL.SELECT_TASK_ID_BY_IDEMPOTENCY, (payload.idempotency_key,))
                row = cur.fetchone() or {}
                existing_id = row.get("id")
                if existing_id is not None:
                    return int(existing_id)
            raise
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] in {1054, 1136}:
                cur.execute(
                    SQL.INSERT_TASK_MINIMAL,
                    (payload.ai_target, payload.message, payload.priority, payload.sessionid),
                )
            else:
                raise
        return int(cur.lastrowid)

    return int(_run_with_cursor(settings, op))


def insert_task_from_telegram(
    settings: Settings,
    ai_target: str,
    message: str,
    chat_id: str,
    user_id: str,
    idempotency_key: Optional[str] = None,
    sessionid: Optional[str] = None,
) -> int:
    return insert_task(
        settings,
        TaskInsert(
            ai_target=ai_target,
            message=message,
            priority=0,
            source_channel="telegram",
            source_chat_id=str(chat_id),
            source_user_id=str(user_id),
            idempotency_key=idempotency_key,
            sessionid=sessionid,
        ),
    )


def get_task_status(settings: Settings, task_id: int) -> Optional[Dict[str, Any]]:
    def op(cur: Any) -> Optional[Dict[str, Any]]:
        cur.execute(SQL.SELECT_TASK_BY_ID, (task_id,))
        row = cur.fetchone()
        return row

    return _run_with_cursor(settings, op)


def fetch_undelivered_feedback(settings: Settings, limit: int = 50) -> List[Dict[str, Any]]:
    def op(cur: Any) -> List[Dict[str, Any]]:
        try:
            cur.execute(SQL.SELECT_UNDELIVERED_FEEDBACK, (limit,))
            return list(cur.fetchall())
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                # Backward compatibility before migration.
                cur.execute(
                    "SELECT id, task_id, source_ai, channel, payload, sessionid, created_at "
                    "FROM ai_feedback ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                rows = list(cur.fetchall())
                for row in rows:
                    row["target_chat_id"] = None
                return rows
            raise

    return _run_with_cursor(settings, op)


def fetch_feedback_by_task_id(settings: Settings, task_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    def op(cur: Any) -> List[Dict[str, Any]]:
        try:
            cur.execute(SQL.SELECT_FEEDBACK_BY_TASK_ID, (str(task_id), limit))
            return list(cur.fetchall())
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                cur.execute(
                    "SELECT id, task_id, source_ai, channel, payload, created_at "
                    "FROM ai_feedback WHERE task_id=%s ORDER BY id ASC LIMIT %s",
                    (str(task_id), limit),
                )
                rows = list(cur.fetchall())
                for row in rows:
                    row["sessionid"] = None
                    row["delivered_tg"] = 0
                    row["delivered_tg_at"] = None
                return rows
            raise

    return _run_with_cursor(settings, op)


def mark_feedback_delivered(settings: Settings, feedback_id: int) -> None:
    def op(cur: Any) -> None:
        try:
            cur.execute(SQL.MARK_FEEDBACK_DELIVERED, (feedback_id,))
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                return
            raise

    _run_with_cursor(settings, op)


def insert_system_feedback(
    settings: Settings,
    task_id: Optional[str],
    source_ai: str,
    payload: str,
    sessionid: Optional[str] = None,
) -> int:
    def op(cur: Any) -> int:
        cur.execute(SQL.INSERT_FEEDBACK, (task_id, source_ai, "system", payload, sessionid))
        return int(cur.lastrowid)

    return int(_run_with_cursor(settings, op))
