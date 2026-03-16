import pytest

from cloud_orchestrator.config import load_settings


def test_missing_bot_token_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "x")
    monkeypatch.setenv("MYSQL_DB", "autoai")
    with pytest.raises(ValueError):
        load_settings(legacy_fallback=False)


def test_legacy_notes_infer_mysql_db_from_user_suffix(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.env"
    legacy.write_text(
        "mysql:\n"
        "  zzb2020.mysql.polardb.rds.aliyuncs.com 3306\n"
        "  edcarwr 数据库 pwd: Car241013@\n"
        "\n"
        "telgbot:\n"
        "  8734725843:ABCDEFGHIJKLMNOPQRSTUVWX\n",
        encoding="utf-8",
    )

    for key in [
        "TELEGRAM_BOT_TOKEN",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DB",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = load_settings(env_file=str(legacy), legacy_fallback=True)
    assert settings.mysql_user == "edcarwr"
    assert settings.mysql_db == "edcar"
