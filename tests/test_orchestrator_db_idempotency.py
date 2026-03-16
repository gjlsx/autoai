import pymysql

from cloud_orchestrator.config import Settings
import cloud_orchestrator.db as db


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="dummy",
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="x",
        mysql_db="autoai",
        api_host="127.0.0.1",
        api_port=18080,
        api_key="",
        default_chat_id="",
        inbound_poll_interval_sec=1.0,
        outbound_poll_interval_sec=2.0,
        telegram_get_updates_timeout_sec=20,
        allowed_ai_targets=("codex", "claude", "gemini"),
    )


class _FakeCursor:
    def __init__(self):
        self.lastrowid = 0
        self._row = None

    def execute(self, sql, args):  # noqa: ANN001
        if "INSERT INTO ai_tasks" in sql:
            raise pymysql.err.IntegrityError(1062, "Duplicate entry")
        if sql == db.SQL.SELECT_TASK_ID_BY_IDEMPOTENCY:
            key = args[0]
            if key == "tg:chat:update":
                self._row = {"id": 123}
            else:
                self._row = None

    def fetchone(self):
        return self._row


def test_insert_task_returns_existing_id_on_idempotency_duplicate(monkeypatch):
    fake_cursor = _FakeCursor()

    def fake_run_with_cursor(settings, operation):  # noqa: ANN001
        _ = settings
        return operation(fake_cursor)

    monkeypatch.setattr(db, "_run_with_cursor", fake_run_with_cursor)

    task_id = db.insert_task(
        _settings(),
        db.TaskInsert(
            ai_target="codex",
            message="hello",
            idempotency_key="tg:chat:update",
            sessionid="tg:chat:codex",
        ),
    )

    assert task_id == 123
