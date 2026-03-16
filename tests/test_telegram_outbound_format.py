from cloud_orchestrator.telegram_outbound import format_feedback


def test_format_feedback_contains_task_and_ai():
    text = format_feedback(
        {"task_id": "11", "source_ai": "claude", "channel": "result", "payload": "done", "sessionid": "s-11"}
    )
    assert "task_id=11" in text
    assert "claude" in text
    assert "done" in text
    assert "sessionid=s-11" in text


def test_format_feedback_extracts_text_from_json_payload_and_strips_ansi():
    payload = (
        '{"event":"output","source":"pty","ai":"codex","task_id":"9","seq":1,"ts":1,'
        '"text":"\\u001b[38;2;200;200;200mhello\\u001b[0m\\r\\nworld"}'
    )
    text = format_feedback({"task_id": "9", "source_ai": "codex", "channel": "db", "payload": payload})
    assert "event=output" in text
    assert "hello\nworld" in text
    assert "\\u001b" not in text
    assert "\x1b" not in text
