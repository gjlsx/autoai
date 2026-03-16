from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class InputEnvelope:
    message: str
    task_id: Optional[str] = None
    source: str = "socket"
    meta: Dict[str, str] = field(default_factory=dict)


class FeedbackEmitter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def emit(self, event: dict) -> None:
        self.queue.put(event)

    def close(self) -> None:
        self.shutdown.set()
        self.queue.join()

    def _loop(self) -> None:
        while not self.shutdown.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._send(event)
            except Exception as exc:
                self._safe_stderr(f"[pty-worker] feedback emit error: {exc}")
            finally:
                self.queue.task_done()

    @staticmethod
    def _safe_stdout(text: str) -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.stdout.flush()

    @staticmethod
    def _safe_stderr(text: str) -> None:
        try:
            print(text, file=sys.stderr)
        except UnicodeEncodeError:
            sys.stderr.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.stderr.flush()

    def _send(self, event: dict) -> None:
        if self.args.feedback_mode == "stdout":
            self._safe_stdout(json.dumps(event, ensure_ascii=False))
            return

        if self.args.feedback_mode == "file":
            if not self.args.feedback_file:
                print("[pty-worker] feedback-file is required when mode=file")
                return
            fp = Path(self.args.feedback_file)
            fp.parent.mkdir(parents=True, exist_ok=True)
            with fp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return

        payload = json.dumps(event, ensure_ascii=False)
        cmd = [
            self.args.python_exe,
            self.args.ai_feedback_path,
            "--source-ai",
            self.args.ai,
        ]
        task_id = event.get("task_id")
        if task_id:
            cmd += ["--task-id", str(task_id)]

        if self.args.feedback_channel == "db":
            cmd += ["--db", payload]
        elif self.args.feedback_channel == "redis":
            cmd += ["--redis", payload]
        else:
            cmd += ["--ask", payload]

        result = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            self._safe_stderr(
                "[pty-worker] ai_feedback failed:",
            )
            self._safe_stderr(
                f"code={result.returncode} detail={(result.stderr or result.stdout or '').strip()}",
            )


class PtyWorker:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.shutdown = threading.Event()
        self.state_lock = threading.Lock()
        self.pty = None
        self.active_task_id: Optional[str] = None
        self.seq = 0
        self.buffer = ""
        self.buffer_task_id: Optional[str] = None
        self.last_flush_ts = time.time()
        self.emitter = FeedbackEmitter(args)

    @staticmethod
    def parse_input(raw: str) -> Optional[InputEnvelope]:
        payload = raw.strip()
        if not payload:
            return None
        if payload.startswith("{"):
            data = json.loads(payload)
            message = str(data.get("message") or data.get("prompt") or "").strip()
            if not message:
                return None
            task_id = data.get("task_id") or data.get("id")
            source = str(data.get("source") or "socket")
            meta = {k: str(v) for k, v in data.items() if k not in {"message", "prompt", "task_id", "id", "source"}}
            return InputEnvelope(
                message=message,
                task_id=str(task_id) if task_id is not None else None,
                source=source,
                meta=meta,
            )
        return InputEnvelope(message=payload, source="socket")

    def _pty_alive(self) -> bool:
        if self.pty is None:
            return False
        try:
            return bool(self.pty.isalive())
        except Exception:
            return False

    @staticmethod
    def resolve_cli_spawn(raw_cli: str) -> tuple[str, Optional[str]]:
        parts = shlex.split(raw_cli, posix=False)
        if not parts:
            raise ValueError("empty --cli command")

        exe = parts[0]
        args = parts[1:]

        candidates = [exe]
        if "." not in Path(exe).name:
            candidates.extend([f"{exe}.cmd", f"{exe}.bat", f"{exe}.exe"])

        resolved = None
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                resolved = path
                break

        if not resolved:
            p = Path(exe)
            if p.exists():
                resolved = str(p)
            else:
                raise FileNotFoundError(f"cannot resolve cli executable from: {raw_cli}")

        suffix = Path(resolved).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            cmdline = subprocess.list2cmdline(["/c", resolved, *args])
            return comspec, cmdline

        cmdline = subprocess.list2cmdline(args) if args else None
        return resolved, cmdline

    def _start_pty_if_needed(self) -> None:
        with self.state_lock:
            if self._pty_alive():
                return

            if os.name != "nt":
                raise RuntimeError("pty_worker currently supports Windows only")

            import winpty

            backend = None
            if self.args.pywinpty_backend == "conpty":
                backend = winpty.Backend.ConPTY
            elif self.args.pywinpty_backend == "winpty":
                backend = winpty.Backend.WinPTY

            if backend is None:
                pty = winpty.PTY(self.args.cols, self.args.rows)
            else:
                pty = winpty.PTY(self.args.cols, self.args.rows, backend=backend)

            appname, cmdline = self.resolve_cli_spawn(self.args.cli)
            if cmdline:
                pty.spawn(appname, cmdline)
            else:
                pty.spawn(appname)
            self.pty = pty
            self._emit_event(
                event_type="session_started",
                task_id=None,
                text=f"spawned cli: {self.args.cli} (app={appname})",
            )

    def _emit_event(self, event_type: str, task_id: Optional[str], text: str, source: str = "pty") -> None:
        self.seq += 1
        event = {
            "event": event_type,
            "source": source,
            "ai": self.args.ai,
            "task_id": task_id,
            "seq": self.seq,
            "ts": int(time.time()),
            "text": text,
        }
        self.emitter.emit(event)

    def _flush_buffer_locked(self) -> None:
        if not self.buffer:
            return
        text = self.buffer
        task_id = self.buffer_task_id
        self.buffer = ""
        self.buffer_task_id = None
        self.last_flush_ts = time.time()
        self._emit_event("output", task_id, text)

    def _append_output(self, task_id: Optional[str], chunk: str) -> None:
        now = time.time()
        with self.state_lock:
            if self.buffer and self.buffer_task_id != task_id:
                self._flush_buffer_locked()
            self.buffer_task_id = task_id
            self.buffer += chunk
            if len(self.buffer) >= self.args.min_event_chars:
                self._flush_buffer_locked()
                return
            if now - self.last_flush_ts >= self.args.max_event_delay_sec:
                self._flush_buffer_locked()

    def _reader_loop(self) -> None:
        while not self.shutdown.is_set():
            try:
                self._start_pty_if_needed()
                pty = self.pty
                if pty is None:
                    time.sleep(self.args.poll_interval_sec)
                    continue

                chunk = pty.read(self.args.read_size, blocking=False)
                if chunk:
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode("utf-8", errors="replace")
                    with self.state_lock:
                        task_id = self.active_task_id
                    self._append_output(task_id, str(chunk))
                else:
                    with self.state_lock:
                        if self.buffer and (time.time() - self.last_flush_ts >= self.args.max_event_delay_sec):
                            self._flush_buffer_locked()
                    time.sleep(self.args.poll_interval_sec)
            except Exception as exc:
                self._emit_event("worker_error", self.active_task_id, str(exc), source="worker")
                with self.state_lock:
                    self.pty = None
                time.sleep(0.3)

    def submit(self, envelope: InputEnvelope) -> None:
        self._start_pty_if_needed()
        message = envelope.message.strip()
        if not message:
            return
        with self.state_lock:
            self.active_task_id = envelope.task_id
            pty = self.pty
        if pty is None:
            raise RuntimeError("pty unavailable")
        pty.write(message + "\r\n")
        if self.args.emit_input_events:
            self._emit_event("input", envelope.task_id, message, source=envelope.source)

    def _handle_conn(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                conn.sendall(b"ERR:empty")
                return
            try:
                payload = data.decode("utf-8", errors="replace")
                envelope = self.parse_input(payload)
                if not envelope:
                    conn.sendall(b"ERR:invalid payload")
                    return
                self.submit(envelope)
                conn.sendall(b"OK")
            except Exception as exc:
                conn.sendall(f"ERR:{exc}".encode("utf-8", errors="replace"))

    def serve(self) -> None:
        if self.args.startup_eager:
            self._start_pty_if_needed()

        reader = threading.Thread(target=self._reader_loop, daemon=True)
        reader.start()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.args.host, self.args.port))
            server.listen(self.args.backlog)
            print(
                f"[pty-worker:{self.args.ai}] listening on {self.args.host}:{self.args.port}, "
                f"cli='{self.args.cli}', backend=pywinpty/{self.args.pywinpty_backend}"
            )
            try:
                while True:
                    conn, _ = server.accept()
                    threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
            except KeyboardInterrupt:
                pass
            finally:
                self.shutdown.set()
                with self.state_lock:
                    self._flush_buffer_locked()
                self.emitter.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PTY worker for AI CLI IO on Windows")
    p.add_argument("--ai", required=True, help="ai name, e.g. codex/claude")
    p.add_argument("--cli", required=True, help="CLI command to run in PTY")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9103)
    p.add_argument("--backlog", type=int, default=64)

    p.add_argument("--pywinpty-backend", choices=["auto", "conpty", "winpty"], default="auto")
    p.add_argument("--cols", type=int, default=120)
    p.add_argument("--rows", type=int, default=30)
    p.add_argument("--read-size", type=int, default=1024)
    p.add_argument("--poll-interval-sec", type=float, default=0.05)
    p.add_argument("--min-event-chars", type=int, default=180)
    p.add_argument("--max-event-delay-sec", type=float, default=1.0)
    p.add_argument("--startup-eager", dest="startup_eager", action="store_true")
    p.add_argument("--no-startup-eager", dest="startup_eager", action="store_false")
    p.set_defaults(startup_eager=True)

    p.add_argument("--feedback-mode", choices=["ai_feedback", "file", "stdout"], default="ai_feedback")
    p.add_argument("--feedback-channel", choices=["db", "redis", "ask"], default="db")
    p.add_argument("--feedback-file", default="")
    p.add_argument("--python-exe", default=sys.executable)
    p.add_argument("--ai-feedback-path", default="ai_feedback.py")
    p.add_argument("--emit-input-events", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    worker = PtyWorker(args)
    worker.serve()


if __name__ == "__main__":
    main()
