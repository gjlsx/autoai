import json
import socket
import subprocess
import sys
import time
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _send_payload(port: int, payload: str) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(payload.encode("utf-8"))
        conn.shutdown(socket.SHUT_WR)
        return conn.recv(4096).decode("utf-8", errors="replace")


def test_codex_agent_worker_file_feedback_mode(tmp_path: Path):
    events_file = tmp_path / "events.jsonl"
    repo_root = Path(__file__).resolve().parents[1]
    port = _free_port()

    proc = subprocess.Popen(
        [
            sys.executable,
            "codex_agent_worker.py",
            "--ai",
            "codex",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--feedback-mode",
            "file",
            "--feedback-file",
            str(events_file),
            "--sdk-provider",
            "mock",
            "--app-provider",
            "mock",
            "--sdk-targets",
            "codex_sdk",
            "--app-targets",
            "codex_app",
            "--emit-input-events",
        ],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 8
        accepted = False
        while time.time() < deadline:
            try:
                resp1 = _send_payload(port, '{"task_id":"t-sdk","target":"codex_sdk","message":"hello sdk"}')
                resp2 = _send_payload(port, '{"task_id":"t-app","target":"codex_app","message":"hello app"}')
                if resp1.startswith("OK") and resp2.startswith("OK"):
                    accepted = True
                    break
            except OSError:
                time.sleep(0.1)
        assert accepted, "worker did not accept socket payloads"

        found_sdk = False
        found_app = False
        deadline = time.time() + 10
        while time.time() < deadline:
            if events_file.exists():
                lines = [line for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines() if line]
                for line in lines:
                    event = json.loads(line)
                    text = str(event.get("text") or "")
                    task_id = str(event.get("task_id") or "")
                    if task_id == "t-sdk" and "MOCK_SDK_REPLY:hello sdk" in text:
                        found_sdk = True
                    if task_id == "t-app" and "MOCK_APP_REPLY:hello app" in text:
                        found_app = True
            if found_sdk and found_app:
                break
            time.sleep(0.2)

        assert found_sdk, "missing sdk backend output event"
        assert found_app, "missing app backend output event"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
