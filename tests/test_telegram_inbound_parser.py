from cloud_orchestrator.config import Settings
from cloud_orchestrator.telegram_inbound import parse_command, process_message


def test_parse_to_command():
    target, message = parse_command("/to codex summarize logs")
    assert target == "codex"
    assert message == "summarize logs"


def test_parse_colon_format():
    target, message = parse_command("claude:check errors")
    assert target == "claude"
    assert message == "check errors"


class _DummyTelegram:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id: str, text: str):
        self.sent.append((chat_id, text))


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


def test_process_message_writes_sessionid(monkeypatch):
    captured = {}

    def fake_insert(**kwargs):
        captured.update(kwargs)
        return 123

    monkeypatch.setattr("cloud_orchestrator.telegram_inbound.db.insert_task_from_telegram", fake_insert)

    tg = _DummyTelegram()
    task_id = process_message(
        _settings(),
        tg,
        chat_id="1261596828",
        user_id="u1",
        text="/to codex hello world",
        update_id=88,
    )

    assert task_id == 123
    assert captured["sessionid"] == "tg:1261596828:codex"
