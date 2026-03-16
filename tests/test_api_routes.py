from fastapi.testclient import TestClient

from cloud_orchestrator.config import Settings
from cloud_orchestrator.main import create_app
import cloud_orchestrator.db as db

DEFAULT_KEY = "autoai_min_auth_2026"


def make_settings() -> Settings:
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


def test_healthz():
    app = create_app(settings=make_settings(), start_workers=False)
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_task_accepts_sessionid(monkeypatch):
    captured = {}

    def fake_insert_task(settings, payload):
        _ = settings
        captured["payload"] = payload
        return 77

    monkeypatch.setattr(db, "insert_task", fake_insert_task)

    app = create_app(settings=make_settings(), start_workers=False)
    client = TestClient(app)
    resp = client.post(
        "/api/tasks",
        json={
            "ai_target": "codex",
            "message": "hello",
            "sessionid": "codex:chat-1",
        },
        headers={"x-api-key": DEFAULT_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == 77
    assert captured["payload"].sessionid == "codex:chat-1"


def test_console_page_requires_key():
    app = create_app(settings=make_settings(), start_workers=False)
    client = TestClient(app)
    resp = client.get("/console")
    assert resp.status_code == 401

    resp = client.get("/console?k=bad")
    assert resp.status_code == 401

    resp = client.get(f"/console?k={DEFAULT_KEY}")
    assert resp.status_code == 200
    assert "AutoAI Console" in resp.text
