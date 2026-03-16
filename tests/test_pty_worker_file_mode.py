import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _send_payload(port: int, payload: str) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(payload.encode("utf-8"))
        conn.shutdown(socket.SHUT_WR)
        return conn.recv(4096).decode("utf-8", errors="replace")


@pytest.mark.skipif(os.name != "nt", reason="Windows-only PTY integration test")
def test_pty_worker_file_feedback_mode(tmp_path: Path):
    events_file = tmp_path / "events.jsonl"
    mock_cli = Path(__file__).resolve().parents[1] / "scripts" / "mock_ai_cli.py"
    cli_cmd = subprocess.list2cmdline([sys.executable, str(mock_cli)])
    port = _free_port()

    proc = subprocess.Popen(
        [
            sys.executable,
            "pty_worker.py",
            "--ai",
            "codex",
            "--cli",
            cli_cmd,
            "--port",
            str(port),
            "--feedback-mode",
            "file",
            "--feedback-file",
            str(events_file),
            "--emit-input-events",
            "--max-event-delay-sec",
            "0.3",
            "--min-event-chars",
            "20",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 6
        ok = False
        while time.time() < deadline:
            try:
                resp = _send_payload(port, '{"task_id":"t-1","message":"hello pty"}')
                if resp.startswith("OK"):
                    ok = True
                    break
            except OSError:
                time.sleep(0.1)
        assert ok, "worker did not accept socket payload"

        found_echo = False
        deadline = time.time() + 8
        while time.time() < deadline:
            if events_file.exists():
                lines = [line for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines() if line]
                for line in lines:
                    event = json.loads(line)
                    text = str(event.get("text") or "")
                    if "MOCK_AI_ECHO:hello pty" in text:
                        found_echo = True
                        break
            if found_echo:
                break
            time.sleep(0.2)
        assert found_echo, "did not capture expected PTY output event"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
