from dispatcher import Dispatcher


def test_parse_payload_extracts_sessionid_and_source_ids():
    raw = (
        '{"task_id":"7","target":"codex","message":"hello","sessionid":"s-7",'
        '"source_chat_id":"126","source_user_id":"u7"}'
    )
    task = Dispatcher._parse_payload(raw, source="mysql")
    assert task is not None
    assert task.task_id == "7"
    assert task.sessionid == "s-7"
    assert task.meta["source_chat_id"] == "126"
    assert task.meta["source_user_id"] == "u7"

