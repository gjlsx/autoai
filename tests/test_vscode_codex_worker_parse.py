from vscode_codex_worker import (
    InputEnvelope,
    detect_codex_log_error,
    extract_incremental_text,
    parse_input_envelope,
    resolve_sessionid,
)


def test_parse_input_envelope_json_with_session_fields():
    env = parse_input_envelope(
        '{"task_id":"11","target":"codex","source":"dispatcher","message":"hello",'
        '"sessionid":"codex:s1","source_chat_id":"126","source_user_id":"u1"}'
    )
    assert isinstance(env, InputEnvelope)
    assert env.task_id == "11"
    assert env.target == "codex"
    assert env.source == "dispatcher"
    assert env.message == "hello"
    assert env.sessionid == "codex:s1"
    assert env.source_chat_id == "126"
    assert env.source_user_id == "u1"


def test_resolve_sessionid_generates_when_missing():
    env = InputEnvelope(message="hello", task_id="42", source_chat_id="1261596828")
    sid = resolve_sessionid("codex", env)
    assert sid == "codex:1261596828"


def test_extract_incremental_text_handles_suffix_growth():
    previous = "hello"
    current = "hello\nworld"
    assert extract_incremental_text(previous, current) == "world"


def test_detect_codex_log_error_from_patch_failure():
    line = "2026-03-02 [warning] Failed to apply patches for conversationId=abc error={}"
    assert detect_codex_log_error(line) == line
