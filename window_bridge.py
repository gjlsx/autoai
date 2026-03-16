import argparse
import json
import shlex
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Optional


class WindowBridge:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.ai_process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.cli_cmd = self.resolve_cli_command(self.args.cli)
        self.spawn_mode = self.resolve_spawn_mode()

    def resolve_spawn_mode(self) -> str:
        if self.args.spawn_mode != "auto":
            return self.args.spawn_mode
        exe = Path(self.cli_cmd[0]).name.lower()
        if exe.startswith("codex"):
            return "exec"
        return "interactive"

    def start_ai_process(self) -> None:
        if self.args.no_spawn:
            print(f"[bridge:{self.args.ai}] no-spawn mode, only printing incoming messages")
            return
        if self.spawn_mode != "interactive":
            print(f"[bridge:{self.args.ai}] spawn-mode={self.spawn_mode}, interactive process not started")
            return

        self.ai_process = subprocess.Popen(
            self.cli_cmd,
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            text=True,
            bufsize=1,
        )
        print(f"[bridge:{self.args.ai}] AI CLI started: {' '.join(self.cli_cmd)}")

    @staticmethod
    def resolve_cli_command(raw_cli: str):
        cmd = shlex.split(raw_cli, posix=False)
        if not cmd:
            raise ValueError("empty --cli command")

        exe = cmd[0]
        resolved = None
        candidates = [exe]
        if "." not in exe.split("\\")[-1]:
            candidates.extend([f"{exe}.cmd", f"{exe}.bat", f"{exe}.exe"])

        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                resolved = path
                break

        if resolved:
            cmd[0] = resolved
        return cmd

    def ensure_ai_process(self) -> None:
        if self.args.no_spawn:
            return
        if self.spawn_mode != "interactive":
            return
        if self.ai_process is None:
            self.start_ai_process()
            return
        if self.ai_process.poll() is not None:
            if self.args.auto_restart:
                print(f"[bridge:{self.args.ai}] AI CLI exited, restarting...")
                self.start_ai_process()
            else:
                raise RuntimeError("AI CLI process exited")

    @staticmethod
    def decode_payload(raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        if raw.startswith("{"):
            data = json.loads(raw)
            task_id = data.get("task_id")
            msg = str(data.get("message", "")).strip()
            if task_id:
                return f"[task_id={task_id}] {msg}"
            return msg
        return raw

    def feed_ai(self, text: str) -> None:
        if not text:
            return
        if self.args.no_spawn:
            print(f"[bridge:{self.args.ai}] <- {text}")
            return

        if self.spawn_mode == "exec":
            self.run_exec_once(text)
            print(f"[bridge:{self.args.ai}] dispatched(exec): {text}")
            return

        with self.lock:
            self.ensure_ai_process()
            assert self.ai_process is not None
            if self.ai_process.stdin is None:
                raise RuntimeError("AI CLI stdin unavailable")
            self.ai_process.stdin.write(text + "\n")
            self.ai_process.stdin.flush()
        print(f"[bridge:{self.args.ai}] dispatched: {text}")

    def run_exec_once(self, text: str) -> None:
        cmd = list(self.cli_cmd)
        has_exec = any(token == "exec" for token in cmd[1:])
        if not has_exec:
            cmd.append("exec")
        if self.args.exec_skip_git_check:
            cmd.append("--skip-git-repo-check")
        cmd.append(text)

        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=self.args.exec_timeout,
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip())
        if result.returncode != 0:
            raise RuntimeError(f"exec mode failed, code={result.returncode}")

    def handle_connection(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return
            raw = data.decode("utf-8", errors="replace")
            try:
                message = self.decode_payload(raw)
                if self.spawn_mode == "exec" and not self.args.no_spawn:
                    conn.sendall(b"OK")
                    threading.Thread(target=self.safe_feed_ai, args=(message,), daemon=True).start()
                else:
                    self.feed_ai(message)
                    conn.sendall(b"OK")
            except Exception as exc:
                err = f"ERR:{exc}"
                conn.sendall(err.encode("utf-8", errors="replace"))
                print(f"[bridge:{self.args.ai}] error: {exc}")

    def safe_feed_ai(self, message: str) -> None:
        try:
            self.feed_ai(message)
        except Exception as exc:
            print(f"[bridge:{self.args.ai}] async dispatch error: {exc}")

    def serve(self) -> None:
        self.start_ai_process()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.args.host, self.args.port))
            server.listen(self.args.backlog)
            print(
                f"[bridge:{self.args.ai}] listening on {self.args.host}:{self.args.port}, "
                f"cli='{self.args.cli}', spawn_mode='{self.spawn_mode}'"
            )
            while True:
                conn, _ = server.accept()
                threading.Thread(target=self.handle_connection, args=(conn,), daemon=True).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge tasks from dispatcher socket to AI CLI")
    parser.add_argument("--ai", required=True, help="AI name, e.g. claude/gemini/codex")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--backlog", type=int, default=64)
    parser.add_argument("--cli", required=True, help="AI CLI command, e.g. 'claude'")
    parser.add_argument(
        "--spawn-mode",
        choices=["auto", "interactive", "exec"],
        default="auto",
        help="auto: codex uses exec, others interactive",
    )
    parser.add_argument("--auto-restart", action="store_true", default=True)
    parser.add_argument("--no-spawn", action="store_true", help="Debug mode, do not launch CLI")
    parser.add_argument("--exec-timeout", type=int, default=600, help="timeout seconds for exec mode")
    parser.add_argument("--exec-skip-git-check", action="store_true", default=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    bridge = WindowBridge(args)
    bridge.serve()


if __name__ == "__main__":
    main()
