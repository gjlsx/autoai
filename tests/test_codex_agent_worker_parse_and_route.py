from codex_agent_worker import (
    InputEnvelope,
    parse_input_envelope,
    resolve_backend_from_target,
)


def test_parse_input_envelope_json():
    env = parse_input_envelope('{"task_id":"11","target":"codex_sdk","message":"hello"}')
    assert isinstance(env, InputEnvelope)
    assert env.task_id == "11"
    assert env.target == "codex_sdk"
    assert env.message == "hello"


def test_parse_input_envelope_plain_text():
    env = parse_input_envelope("hello plain")
    assert isinstance(env, InputEnvelope)
    assert env.message == "hello plain"
    assert env.target is None


def test_resolve_backend_from_target():
    assert resolve_backend_from_target("codex_sdk", sdk_targets={"codex_sdk"}, app_targets={"codex_app"}) == "sdk"
    assert resolve_backend_from_target("codex_app", sdk_targets={"codex_sdk"}, app_targets={"codex_app"}) == "app"
    assert resolve_backend_from_target("codex", sdk_targets={"codex_sdk"}, app_targets={"codex_app"}) == "none"
