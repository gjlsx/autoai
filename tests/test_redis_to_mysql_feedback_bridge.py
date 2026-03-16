import json
from argparse import Namespace
from pathlib import Path

from scripts.redis_to_mysql_feedback_bridge import (
    BridgeConfig,
    RedisToMysqlFeedbackBridge,
    apply_dotenv_mysql_defaults,
)


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))


class _FakeMysqlConn:
    def __init__(self):
        self.queries = []
        self.ping_count = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def ping(self, reconnect=True):
        _ = reconnect
        self.ping_count += 1

    def close(self):
        self.closed = True


class _FakeRedis:
    def __init__(self, items):
        self.items = list(items)
        self.retry = []

    def brpop(self, key, timeout=0):
        _ = (key, timeout)
        if not self.items:
            return None
        return ("ai_skill_feedback_events", self.items.pop(0))

    def lpush(self, key, payload):
        self.retry.append((key, payload))


def _cfg() -> BridgeConfig:
    return BridgeConfig(
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_db=0,
        redis_key="ai_skill_feedback_events",
        redis_retry_key="ai_skill_feedback_retry",
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        mysql_db="autoai",
        mysql_table="ai_feedback",
        pop_timeout_sec=1,
        idle_sleep_sec=0.01,
    )


def test_process_one_success(monkeypatch):
    fake_conn = _FakeMysqlConn()
    fake_redis = _FakeRedis(
        [
            json.dumps(
                {
                    "event": "output",
                    "source_ai": "codex",
                    "task_id": "1",
                    "sessionid": "s1",
                    "channel": "db",
                    "payload": "hello",
                }
            )
        ]
    )
    monkeypatch.setattr("scripts.redis_to_mysql_feedback_bridge.redis.Redis", lambda **kwargs: fake_redis)
    monkeypatch.setattr("scripts.redis_to_mysql_feedback_bridge.pymysql.connect", lambda **kwargs: fake_conn)

    bridge = RedisToMysqlFeedbackBridge(_cfg())
    ok = bridge.process_one()
    assert ok is True
    assert any("INSERT INTO ai_feedback" in q[0] for q in fake_conn.queries)
    bridge.close()


def test_process_one_pushes_retry_on_bad_json(monkeypatch):
    fake_conn = _FakeMysqlConn()
    fake_redis = _FakeRedis(["not-json"])
    monkeypatch.setattr("scripts.redis_to_mysql_feedback_bridge.redis.Redis", lambda **kwargs: fake_redis)
    monkeypatch.setattr("scripts.redis_to_mysql_feedback_bridge.pymysql.connect", lambda **kwargs: fake_conn)

    bridge = RedisToMysqlFeedbackBridge(_cfg())
    ok = bridge.process_one()
    assert ok is False
    assert fake_redis.retry
    assert fake_redis.retry[0][0] == "ai_skill_feedback_retry"
    bridge.close()


def test_apply_dotenv_mysql_defaults(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "MYSQL_HOST=zzb2020.mysql.polardb.rds.aliyuncs.com",
                "MYSQL_PORT=3306",
                "MYSQL_USER=edcarwr",
                "MYSQL_PASSWORD=Car241013@",
                "MYSQL_DB=edcar",
            ]
        ),
        encoding="utf-8",
    )
    args = Namespace(
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="",
        mysql_db="autoai",
    )
    apply_dotenv_mysql_defaults(args, dotenv_path=env)
    assert args.mysql_host == "zzb2020.mysql.polardb.rds.aliyuncs.com"
    assert args.mysql_user == "edcarwr"
    assert args.mysql_password == "Car241013@"
    assert args.mysql_db == "edcar"


def test_apply_dotenv_mysql_defaults_legacy_note_lines(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "zzb2020.mysql.polardb.rds.aliyuncs.com 3306",
                "edcarwr xxx pwd:Car241013@",
            ]
        ),
        encoding="utf-8",
    )
    args = Namespace(
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="",
        mysql_db="autoai",
    )
    apply_dotenv_mysql_defaults(args, dotenv_path=env)
    assert args.mysql_host == "zzb2020.mysql.polardb.rds.aliyuncs.com"
    assert args.mysql_user == "edcarwr"
    assert args.mysql_password == "Car241013@"
    assert args.mysql_db == "edcar"
