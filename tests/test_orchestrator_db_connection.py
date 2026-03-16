from cloud_orchestrator.config import Settings
import cloud_orchestrator.db as db


class FakeConn:
    def __init__(self, *, fail_ping_once: bool = False):
        self.fail_ping_once = fail_ping_once
        self.closed = False

    def ping(self, reconnect: bool = True):
        if self.fail_ping_once:
            self.fail_ping_once = False
            raise RuntimeError("ping failed")

    def close(self):
        self.closed = True


def make_settings() -> Settings:
    return Settings(
        telegram_bot_token="x",
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
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


def test_connect_reuses_singleton_connection(monkeypatch):
    created = []

    def fake_connect(**kwargs):
        _ = kwargs
        conn = FakeConn()
        created.append(conn)
        return conn

    db.reset_connection_cache()
    monkeypatch.setattr(db.pymysql, "connect", fake_connect)

    settings = make_settings()
    c1 = db.connect(settings)
    c2 = db.connect(settings)

    assert c1 is c2
    assert len(created) == 1


def test_connect_reconnects_when_ping_failed(monkeypatch):
    first = FakeConn(fail_ping_once=True)
    second = FakeConn()
    queue = [first, second]

    def fake_connect(**kwargs):
        _ = kwargs
        return queue.pop(0)

    db.reset_connection_cache()
    monkeypatch.setattr(db.pymysql, "connect", fake_connect)

    settings = make_settings()
    c1 = db.connect(settings)
    c2 = db.connect(settings)

    assert c1 is first
    assert c2 is second
    assert first.closed is True
