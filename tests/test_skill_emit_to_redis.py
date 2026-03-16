import json
import sys

from scripts import skill_emit_to_redis as mod


def test_make_event_fields():
    args = mod.build_parser().parse_args(
        [
            "--source-ai",
            "codex",
            "--task-id",
            "101",
            "--sessionid",
            "s1",
            "--event",
            "output",
            "--text",
            "hello",
        ]
    )
    ev = mod.make_event(args)
    assert ev["source_ai"] == "codex"
    assert ev["task_id"] == "101"
    assert ev["sessionid"] == "s1"
    assert ev["payload"] == "hello"


def test_main_pushes_redis(monkeypatch):
    calls = []

    class FakeRedis:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def lpush(self, key, value):
            calls.append(("lpush", key, json.loads(value)))

    monkeypatch.setattr(mod.redis, "Redis", FakeRedis)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "skill_emit_to_redis.py",
            "--source-ai",
            "codex",
            "--task-id",
            "9",
            "--sessionid",
            "s9",
            "--text",
            "done",
            "--redis-key",
            "k1",
        ],
    )
    mod.main()
    assert calls[1][0] == "lpush"
    assert calls[1][1] == "k1"
    assert calls[1][2]["payload"] == "done"

