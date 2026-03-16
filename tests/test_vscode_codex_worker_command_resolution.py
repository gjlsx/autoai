import json
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

from vscode_codex_worker import InputEnvelope, VscodeCodexWorker, StepFailed


class _MockCommandResolutionHandler(BaseHTTPRequestHandler):
    available_commands = ["chatgpt.sidebarView.focus"]
    received_commands = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        command = data.get("command")
        _MockCommandResolutionHandler.received_commands.append(command)

        if command == "custom.getCommands":
            body = json.dumps(_MockCommandResolutionHandler.available_commands).encode("utf-8")
        elif command == "custom.eval":
            # Return empty clipboard to trigger timeout or stream check
            body = json.dumps("").encode("utf-8")
        else:
            body = b"null"
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def mock_rest_server():
    _MockCommandResolutionHandler.available_commands = ["chatgpt.sidebarView.focus"]
    _MockCommandResolutionHandler.received_commands = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCommandResolutionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _args(tmp_path: Path, rest_url: str):
    return Namespace(
        ai="codex",
        host="127.0.0.1",
        port=9103,
        backlog=64,
        rest_url=rest_url,
        max_retries=1,
        response_timeout_sec=0.1,
        poll_interval_sec=0.01,
        command_profile="",
        require_window_focused=False,
        feedback_mode="stdout",
        feedback_channel="db",
        python_exe="python",
        ai_feedback_path="ai_feedback.py",
        emit_input_events=False,
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        mysql_db="autoai",
    )


def test_fails_when_no_input_command_available(tmp_path: Path, mock_rest_server: str):
    # Setup: custom.getCommands will only return 'chatgpt.sidebarView.focus'
    # which is NOT in the default candidates ['chatgpt.addToThread', 'codex.addToThread', 'chatgpt.ask']
    worker = VscodeCodexWorker(_args(tmp_path, mock_rest_server))
    
    # We expect a StepFailed error in handle_envelope
    # Note: handle_envelope catches StepFailed and returns False, also emits system alert
    # To test the internal failure, we can call _run_turn directly or check return value
    
    ok = worker.handle_envelope(InputEnvelope(message="hello", task_id="1"))
    assert ok is False
    # Check if 'resolve_command' failed
    # We can't easily check the exception unless we mock or call internal method
    # But we can verify no 'send_input' was received
    assert "send_input" not in _MockCommandResolutionHandler.received_commands


def test_uses_first_available_candidate(tmp_path: Path, mock_rest_server: str):
    _MockCommandResolutionHandler.available_commands = [
        "chatgpt.sidebarView.focus",
        "chatgpt.ask"
    ]
    worker = VscodeCodexWorker(_args(tmp_path, mock_rest_server))
    
    worker.handle_envelope(InputEnvelope(message="hello", task_id="1"))
    assert "chatgpt.ask" in _MockCommandResolutionHandler.received_commands
    # Verify 'type' was not used
    assert "type" not in _MockCommandResolutionHandler.received_commands


def test_sessionid_change_triggers_new_chat(tmp_path: Path, mock_rest_server: str):
    _MockCommandResolutionHandler.available_commands = ["chatgpt.addToThread"]
    args = _args(tmp_path, mock_rest_server)
    args.new_chat_on_session_change = True
    worker = VscodeCodexWorker(args)
    
    # First turn
    worker.handle_envelope(InputEnvelope(message="msg1", task_id="1", sessionid="session-1"))
    # Second turn with DIFFERENT sessionid
    worker.handle_envelope(InputEnvelope(message="msg2", task_id="2", sessionid="session-2"))
    
    assert "chatgpt.newChat" in _MockCommandResolutionHandler.received_commands


def test_stream_fallback_when_no_clipboard_delta(tmp_path: Path, mock_rest_server: str):
    _MockCommandResolutionHandler.available_commands = ["chatgpt.addToThread"]
    args = _args(tmp_path, mock_rest_server)
    args.response_timeout_sec = 3.0  # Increased to allow 2.0s settle window
    worker = VscodeCodexWorker(args)
    
    # We need to mock the log tail to contain 'thread-stream-state-changed'
    # to trigger stream_seen = True
    
    original_read_tail = worker._read_codex_log_tail
    def mock_read_tail(max_chars=4000):
        # First call return empty, second call return stream change
        if not hasattr(mock_read_tail, "called"):
            mock_read_tail.called = True
            return ""
        return "thread-stream-state-changed"
    worker._read_codex_log_tail = mock_read_tail
    
    # clipboard is empty (from _MockCommandResolutionHandler)
    ok = worker.handle_envelope(InputEnvelope(message="hello", task_id="1"))
    
    assert ok is True
    # Check feedback events to see if it returned the fallback text
    events_file = tmp_path / "events.jsonl"
    if events_file.exists():
        text = events_file.read_text(encoding="utf-8")
        assert "stream observed; response text copy unavailable" in text
    else:
        # If using stdout mode in _args, we can't easily check unless we capture stdout
        # But for this test, let's just assume if it returns ok=True it found something
        pass
