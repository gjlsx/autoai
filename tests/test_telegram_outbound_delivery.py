from cloud_orchestrator.config import Settings
from cloud_orchestrator.telegram_outbound import deliver_once


class DummyTelegram:
    def __init__(self, fail_chat_ids=None):
        self.fail_chat_ids = set(fail_chat_ids or [])
        self.sent = []

    def send_message(self, chat_id: str, text: str):
        if str(chat_id) in self.fail_chat_ids:
            raise RuntimeError("mock send failed")
        self.sent.append((str(chat_id), text))
        return {"ok": True}


def make_settings(default_chat_id: str = "") -> Settings:
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
        default_chat_id=default_chat_id,
        inbound_poll_interval_sec=1.0,
        outbound_poll_interval_sec=2.0,
        telegram_get_updates_timeout_sec=20,
        allowed_ai_targets=("codex", "claude", "gemini"),
    )


def test_deliver_once_marks_delivered_with_task_chat(monkeypatch):
    rows = [
        {
            "id": 101,
            "task_id": "11",
            "source_ai": "codex",
            "channel": "db",
            "payload": "done",
            "target_chat_id": "123",
        }
    ]
    marked = []

    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.fetch_undelivered_feedback",
        lambda settings, limit=20: rows,
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.mark_feedback_delivered",
        lambda settings, feedback_id: marked.append(feedback_id),
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.insert_system_feedback",
        lambda settings, task_id, source_ai, payload: 1,
    )

    tg = DummyTelegram()
    delivered = deliver_once(make_settings(default_chat_id=""), tg, batch_size=20)

    assert delivered == 1
    assert len(tg.sent) == 1
    assert tg.sent[0][0] == "123"
    assert marked == [101]


def test_deliver_once_uses_default_chat_id_when_task_chat_missing(monkeypatch):
    rows = [
        {
            "id": 102,
            "task_id": "12",
            "source_ai": "codex",
            "channel": "db",
            "payload": "hello",
            "target_chat_id": None,
        }
    ]
    marked = []

    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.fetch_undelivered_feedback",
        lambda settings, limit=20: rows,
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.mark_feedback_delivered",
        lambda settings, feedback_id: marked.append(feedback_id),
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.insert_system_feedback",
        lambda settings, task_id, source_ai, payload: 1,
    )

    tg = DummyTelegram()
    delivered = deliver_once(make_settings(default_chat_id="999"), tg, batch_size=20)

    assert delivered == 1
    assert len(tg.sent) == 1
    assert tg.sent[0][0] == "999"
    assert marked == [102]


def test_deliver_once_continues_after_single_send_failure(monkeypatch):
    rows = [
        {
            "id": 201,
            "task_id": "21",
            "source_ai": "codex",
            "channel": "db",
            "payload": "first",
            "target_chat_id": "bad_chat",
        },
        {
            "id": 202,
            "task_id": "22",
            "source_ai": "claude",
            "channel": "db",
            "payload": "second",
            "target_chat_id": "ok_chat",
        },
    ]
    marked = []
    system_errors = []

    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.fetch_undelivered_feedback",
        lambda settings, limit=20: rows,
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.mark_feedback_delivered",
        lambda settings, feedback_id: marked.append(feedback_id),
    )
    monkeypatch.setattr(
        "cloud_orchestrator.telegram_outbound.db.insert_system_feedback",
        lambda settings, task_id, source_ai, payload: system_errors.append((task_id, source_ai, payload)) or 1,
    )

    tg = DummyTelegram(fail_chat_ids={"bad_chat"})
    delivered = deliver_once(make_settings(default_chat_id=""), tg, batch_size=20)

    assert delivered == 1
    assert marked == [202]
    assert len(tg.sent) == 1
    assert tg.sent[0][0] == "ok_chat"
    assert len(system_errors) == 1
    assert "feedback_id=201" in system_errors[0][2]
