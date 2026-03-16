import json
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vscode_codex_worker import InputEnvelope, VscodeCodexWorker


class _MockRestHandler(BaseHTTPRequestHandler):
    commands = []
    clipboard_values = ["", "assistant done", "assistant done"]
    clipboard_index = 0

    def log_message(self, format, *args):  # noqa: A003
        _ = format
        _ = args
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        command = data.get("command")
        _MockRestHandler.commands.append(command)

        if command == "custom.getCommands":
            body = json.dumps(["chatgpt.addToThread"]).encode("utf-8")
        elif command == "custom.eval":
            idx = _MockRestHandler.clipboard_index
            if idx < len(_MockRestHandler.clipboard_values):
                out = _MockRestHandler.clipboard_values[idx]
            else:
                out = _MockRestHandler.clipboard_values[-1]
            _MockRestHandler.clipboard_index = idx + 1
            body = json.dumps(out).encode("utf-8")
        else:
            body = b"null"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _args(tmp_path: Path, rest_url: str):
    return Namespace(
        ai="codex",
        host="127.0.0.1",
        port=9103,
        backlog=64,
        rest_url=rest_url,
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


def test_worker_with_mock_rest_server(tmp_path: Path):
    _MockRestHandler.commands = []
    _MockRestHandler.clipboard_index = 0

    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockRestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rest_url = f"http://127.0.0.1:{server.server_address[1]}"
        worker = VscodeCodexWorker(_args(tmp_path, rest_url=rest_url))
        ok = worker.handle_envelope(InputEnvelope(message="hello", task_id="1", sessionid="s-1"))
        worker.emitter.close()
        assert ok is True
        assert "chatgpt.addToThread" in _MockRestHandler.commands

        events_file = tmp_path / "events.jsonl"
        text = events_file.read_text(encoding="utf-8")
        assert '"event": "output"' in text
        assert "assistant done" in text
    finally:
        server.shutdown()
        server.server_close()
