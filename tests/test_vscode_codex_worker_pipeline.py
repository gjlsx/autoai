from argparse import Namespace
from pathlib import Path

import pytest

from vscode_codex_worker import InputEnvelope, StepFailed, VscodeCodexWorker


def _args(tmp_path: Path, **overrides):
    base = dict(
        ai="codex",
        host="127.0.0.1",
        port=9103,
        backlog=64,
        rest_url="http://127.0.0.1:49818",
        max_retries=3,
        response_timeout_sec=5.0,
        poll_interval_sec=0.01,
        command_profile="",
        require_window_focused=False,
        feedback_mode="file",
        feedback_channel="db",
        feedback_file=str(tmp_path / "events.jsonl"),
        python_exe="python",
        ai_feedback_path="ai_feedback.py",
        emit_input_events=False,
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        mysql_db="autoai",
    )
    base.update(overrides)
    return Namespace(**base)


def test_run_turn_uses_expected_command_pipeline(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path))
    calls = []
    clipboard_values = ["", "assistant final answer"]
    index = {"i": 0}

    def fake_invoke(command: str, args=None):
        calls.append((command, args))
        if command == "custom.getCommands":
            return ["chatgpt.addToThread", "chatgpt.newChat"]
        if command == "custom.eval":
            i = index["i"]
            if i < len(clipboard_values):
                out = clipboard_values[i]
            else:
                out = clipboard_values[-1]
            index["i"] = i + 1
            return out
        return None

    monkeypatch.setattr(worker, "_invoke_command", fake_invoke)
    output = worker._run_turn(message="say hello", sessionid="sid-1")

    assert output == "assistant final answer"
    commands_called = [item[0] for item in calls]
    assert "chatgpt.addToThread" in commands_called
    assert "type" not in commands_called
    assert "workbench.action.chat.submit" not in commands_called


def test_handle_envelope_retries_and_escalates_after_three_failures(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path, max_retries=3))
    attempts = {"submit": 0}
    alerts = []
    failed_updates = []

    def fake_invoke(command: str, args=None):
        _ = args
        if command == "custom.getCommands":
            return ["chatgpt.addToThread"]
        if command == "chatgpt.addToThread":
            attempts["submit"] += 1
            raise RuntimeError("submit failed")
        if command == "custom.eval":
            return ""
        return None

    monkeypatch.setattr(worker, "_invoke_command", fake_invoke)
    monkeypatch.setattr(worker, "_emit_system_alert", lambda **kwargs: alerts.append(kwargs))
    monkeypatch.setattr(worker, "_mark_task_failed", lambda task_id, error: failed_updates.append((task_id, error)))

    ok = worker.handle_envelope(InputEnvelope(message="hello", task_id="99", sessionid="s-99"))
    assert ok is False
    assert attempts["submit"] == 3
    assert alerts
    assert alerts[0]["step"] == "send_input"
    assert failed_updates
    assert failed_updates[0][0] == "99"


def test_handle_envelope_marks_running_then_completed(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path))
    statuses = []

    monkeypatch.setattr(worker, "_ensure_session", lambda sessionid: sessionid)
    monkeypatch.setattr(worker, "_run_turn", lambda **kwargs: "done")
    monkeypatch.setattr(worker, "_emit_feedback_event", lambda **kwargs: kwargs)
    monkeypatch.setattr(worker, "_mark_task_status", lambda task_id, status: statuses.append((task_id, status)))

    ok = worker.handle_envelope(InputEnvelope(message="hello", task_id="101", sessionid="s-101"))
    assert ok is True
    assert statuses == [("101", "running"), ("101", "completed")]


def test_ensure_session_does_not_new_chat_by_default(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path))
    calls = []

    monkeypatch.setattr(worker, "_run_step", lambda *args, **kwargs: calls.append((args, kwargs)))
    worker._ensure_session("sid-a")
    worker._ensure_session("sid-b")

    assert worker.active_sessionid == "sid-b"
    assert calls == []


def test_ensure_session_new_chat_when_enabled(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path, new_chat_on_session_change=True))
    calls = []

    monkeypatch.setattr(worker, "_run_step", lambda *args, **kwargs: calls.append((args, kwargs)))
    worker._ensure_session("sid-a")
    worker._ensure_session("sid-b")

    assert worker.active_sessionid == "sid-b"
    assert len(calls) == 1
    assert calls[0][0][0] == "new_chat"


def test_run_turn_stream_fallback_when_no_clipboard_delta(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(
        _args(
            tmp_path,
            response_timeout_sec=5.0,
            poll_interval_sec=0.01,
            command_profile="",
        )
    )
    worker.command_profile["stream_fallback_output"] = True
    worker.command_profile["stream_fallback_text"] = "stream observed fallback"

    def fake_run_step(step: str, command: str, args=None):
        if command == "custom.getCommands":
            return ["chatgpt.addToThread"]
        return None

    monkeypatch.setattr(worker, "_snapshot_chat_text", lambda: "")
    monkeypatch.setattr(worker, "_run_step", fake_run_step)
    tails = ["base-log", "thread-stream-state-changed", "thread-stream-state-changed"]

    def fake_tail(max_chars=4000):
        if tails:
            return tails.pop(0)
        return "thread-stream-state-changed"

    # We need to make sure the time elapsed since last_stream_seen is >= 2.0s
    # In the test, we can mock time.time() or just wait.
    # But for simplicity, let's mock the check.
    
    monkeypatch.setattr(worker, "_read_codex_log_tail", fake_tail)
    
    import time
    original_time = time.time
    # Mock time to jump 3 seconds after stream is seen
    time_mock = {"t": 1000.0}
    def fake_time():
        t = time_mock["t"]
        time_mock["t"] += 0.5 # increment a bit each call
        if len(tails) == 0:
            time_mock["t"] += 3.0 # Jump after we saw stream
        return t
    monkeypatch.setattr(time, "time", fake_time)

    try:
        out = worker._run_turn(message="hello", sessionid="sid-stream")
        assert out == "stream observed fallback"
    finally:
        monkeypatch.setattr(time, "time", original_time)


def test_run_turn_fails_fast_when_vscode_window_not_focused(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path, max_retries=2, response_timeout_sec=5.0, require_window_focused=True))

    def fake_run_step(step: str, command: str, args=None):
        _ = (command, args)
        if step == "read_window_state":
            return '{"focused": false, "active": false}'
        return None

    monkeypatch.setattr(worker, "_run_step", fake_run_step)

    with pytest.raises(StepFailed) as exc:
        worker._run_turn(message="hello", sessionid="sid-focus-fail")

    assert exc.value.step == "window_focus"


def test_run_turn_recovers_when_window_focus_becomes_true(monkeypatch, tmp_path: Path):
    worker = VscodeCodexWorker(_args(tmp_path, max_retries=3, poll_interval_sec=0.01, require_window_focused=True))

    focus_states = iter(
        [
            '{"focused": false, "active": false}',
            '{"focused": true, "active": true}',
        ]
    )
    calls = []
    snapshots = iter(["", "assistant final answer"])

    def fake_run_step(step: str, command: str, args=None):
        calls.append((step, command, args))
        if step == "read_window_state":
            return next(focus_states, '{"focused": true, "active": true}')
        if step == "read_clipboard":
            return ""
        if command == "custom.getCommands":
            return ["chatgpt.addToThread"]
        return None

    monkeypatch.setattr(worker, "_run_step", fake_run_step)
    monkeypatch.setattr(worker, "_read_codex_log_tail", lambda: "same-log")
    monkeypatch.setattr(worker, "_snapshot_chat_text", lambda: next(snapshots, "assistant final answer"))

    out = worker._run_turn(message="hello", sessionid="sid-focus-ok")
    assert out == "assistant final answer"
    assert any(step.startswith("focus_retry_") for step, _, _ in calls)
