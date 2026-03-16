from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set


@dataclass
class InputEnvelope:
    message: str
    task_id: Optional[str] = None
    target: Optional[str] = None
    source: str = "socket"
    meta: Dict[str, str] = field(default_factory=dict)


def parse_targets_csv(raw: str, fallback: Set[str]) -> Set[str]:
    names = {item.strip().lower() for item in (raw or "").split(",") if item.strip()}
    return names or set(fallback)


def parse_input_envelope(raw: str) -> Optional[InputEnvelope]:
    payload = raw.strip()
    if not payload:
        return None

    if payload.startswith("{"):
        data = json.loads(payload)
        message = str(data.get("message") or data.get("prompt") or data.get("input") or "").strip()
        if not message:
            return None
        task_id = data.get("task_id") or data.get("id")
        target = data.get("target")
        source = str(data.get("source") or "socket")
        meta = {
            k: str(v)
            for k, v in data.items()
            if k not in {"message", "prompt", "input", "task_id", "id", "target", "source"}
        }
        return InputEnvelope(
            message=message,
            task_id=str(task_id) if task_id is not None else None,
            target=str(target).strip().lower() if target is not None else None,
            source=source,
            meta=meta,
        )

    return InputEnvelope(message=payload, source="socket")


def resolve_backend_from_target(target: Optional[str], sdk_targets: Set[str], app_targets: Set[str]) -> str:
    if not target:
        return "none"
    name = target.strip().lower()
    if name in sdk_targets:
        return "sdk"
    if name in app_targets:
        return "app"
    return "none"


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
                self._safe_stderr(f"[codex-agent-worker] feedback emit error: {exc}")
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
                self._safe_stderr("[codex-agent-worker] feedback-file is required when mode=file")
                return
            fp = Path(self.args.feedback_file)
            fp.parent.mkdir(parents=True, exist_ok=True)
            with fp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return

        payload = json.dumps(event, ensure_ascii=False)
        source_ai = str(event.get("source_ai") or self.args.ai)
        cmd = [
            self.args.python_exe,
            self.args.ai_feedback_path,
            "--source-ai",
            source_ai,
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
            detail = (result.stderr or result.stdout or "").strip()
            self._safe_stderr(f"[codex-agent-worker] ai_feedback failed code={result.returncode} detail={detail}")


class BaseBackend:
    def run_turn(self, envelope: InputEnvelope) -> str:
        raise NotImplementedError


class MockBackend(BaseBackend):
    def __init__(self, kind: str):
        self.kind = kind
        self.thread_id = f"mock-{kind}-{uuid.uuid4().hex[:8]}"
        self.turn = 0
        self.lock = threading.Lock()

    def run_turn(self, envelope: InputEnvelope) -> str:
        with self.lock:
            self.turn += 1
            if self.kind == "sdk":
                prefix = "MOCK_SDK_REPLY"
            else:
                prefix = "MOCK_APP_REPLY"
            return f"{prefix}:{envelope.message}"


class SubprocessBackend(BaseBackend):
    def __init__(self, kind: str, command_template: str, timeout_sec: float, cwd: Path):
        if not command_template.strip():
            raise ValueError(f"{kind} command is required when provider=subprocess")
        self.kind = kind
        self.command_template = command_template
        self.timeout_sec = timeout_sec
        self.cwd = cwd
        self.thread_id = uuid.uuid4().hex
        self.turn = 0
        self.lock = threading.Lock()

    def _build_command(self, message: str, turn: int) -> list[str]:
        if any(token in self.command_template for token in ("{message}", "{thread_id}", "{turn}")):
            cmd_text = self.command_template.format(message=message, thread_id=self.thread_id, turn=turn)
            return shlex.split(cmd_text, posix=False)

        args = shlex.split(self.command_template, posix=False)
        args.append(message)
        return args

    def run_turn(self, envelope: InputEnvelope) -> str:
        with self.lock:
            self.turn += 1
            turn = self.turn
            cmd = self._build_command(envelope.message, turn)

        env = os.environ.copy()
        env["AUTOAI_THREAD_ID"] = self.thread_id
        env["AUTOAI_TURN_INDEX"] = str(turn)
        env["AUTOAI_BACKEND_KIND"] = self.kind

        result = subprocess.run(
            cmd,
            cwd=str(self.cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_sec,
        )
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        if result.returncode != 0:
            raise RuntimeError(f"subprocess backend failed: rc={result.returncode} output={output}")
        if not output:
            return f"SUBPROCESS_{self.kind.upper()}_OK:turn={turn}"
        return output


class AppServerBackend(BaseBackend):
    def __init__(self, args: argparse.Namespace):
        if not args.app_server_url.strip():
            raise ValueError("--app-server-url is required when app provider is app_server")
        self.url = args.app_server_url
        self.timeout_sec = float(args.app_server_timeout_sec)
        self.initialize_method = args.app_initialize_method
        self.thread_start_method = args.app_thread_start_method
        self.thread_resume_method = args.app_thread_resume_method
        self.turn_start_method = args.app_turn_start_method
        self.resume_thread_id = args.app_resume_thread_id.strip() or None
        self.initialized = False
        self.thread_id: Optional[str] = None
        self.turn = 0
        self.rpc_id = 1
        self.lock = threading.Lock()

    def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self.rpc_id,
            "method": method,
            "params": params,
        }
        self.rpc_id += 1
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"app-server request failed: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"app-server invalid json: {body[:300]}") from exc

        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"app-server error: {data.get('error')}")
        if not isinstance(data, dict):
            raise RuntimeError(f"app-server invalid response: {body[:300]}")
        return data

    @staticmethod
    def _find_first_string(value: Any) -> Optional[str]:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for v in value.values():
                found = AppServerBackend._find_first_string(v)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = AppServerBackend._find_first_string(item)
                if found:
                    return found
        return None

    @staticmethod
    def _find_thread_id(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            for key in ("thread_id", "threadId", "id"):
                if key in value and str(value[key]).strip():
                    return str(value[key]).strip()
            for v in value.values():
                found = AppServerBackend._find_thread_id(v)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = AppServerBackend._find_thread_id(item)
                if found:
                    return found
        return None

    def _ensure_thread(self) -> None:
        if not self.initialized:
            self._rpc(self.initialize_method, {"client": {"name": "autoai", "version": "1.0"}})
            self.initialized = True

        if self.thread_id:
            return

        if self.resume_thread_id:
            resumed = self._rpc(self.thread_resume_method, {"thread_id": self.resume_thread_id})
            found = self._find_thread_id(resumed)
            self.thread_id = found or self.resume_thread_id
            return

        started = self._rpc(self.thread_start_method, {})
        found = self._find_thread_id(started)
        self.thread_id = found or uuid.uuid4().hex

    def run_turn(self, envelope: InputEnvelope) -> str:
        with self.lock:
            self._ensure_thread()
            self.turn += 1
            thread_id = self.thread_id

        resp = self._rpc(
            self.turn_start_method,
            {
                "thread_id": thread_id,
                "input": envelope.message,
            },
        )
        text = self._find_first_string(resp.get("result"))
        if text:
            return text
        return json.dumps(resp.get("result") or resp, ensure_ascii=False)


class CodexAgentWorker:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.shutdown = threading.Event()
        self.seq = 0
        self.seq_lock = threading.Lock()
        self.backends_lock = threading.Lock()
        self.backends: Dict[str, BaseBackend] = {}
        self.sdk_targets = parse_targets_csv(args.sdk_targets, {"codex_sdk"})
        self.app_targets = parse_targets_csv(args.app_targets, {"codex_app"})
        self.emitter = FeedbackEmitter(args)

    def _emit_event(
        self,
        *,
        event_type: str,
        text: str,
        task_id: Optional[str],
        source: str,
        source_ai: Optional[str],
        backend: Optional[str],
        target: Optional[str],
    ) -> None:
        with self.seq_lock:
            self.seq += 1
            seq = self.seq

        event = {
            "event": event_type,
            "source": source,
            "ai": self.args.ai,
            "source_ai": source_ai or self.args.ai,
            "task_id": task_id,
            "target": target,
            "backend": backend,
            "seq": seq,
            "ts": int(time.time()),
            "text": text,
        }
        self.emitter.emit(event)

    def _build_backend(self, kind: str) -> BaseBackend:
        if kind == "sdk":
            provider = self.args.sdk_provider
            if provider == "mock":
                return MockBackend("sdk")
            if provider == "subprocess":
                return SubprocessBackend("sdk", self.args.sdk_command, self.args.backend_timeout_sec, Path.cwd())
            raise ValueError(f"unsupported sdk provider: {provider}")

        if kind == "app":
            provider = self.args.app_provider
            if provider == "mock":
                return MockBackend("app")
            if provider == "subprocess":
                return SubprocessBackend("app", self.args.app_command, self.args.backend_timeout_sec, Path.cwd())
            if provider == "app_server":
                return AppServerBackend(self.args)
            raise ValueError(f"unsupported app provider: {provider}")

        raise ValueError(f"unknown backend kind: {kind}")

    def _get_backend(self, kind: str) -> BaseBackend:
        with self.backends_lock:
            backend = self.backends.get(kind)
            if backend is None:
                backend = self._build_backend(kind)
                self.backends[kind] = backend
            return backend

    def _resolve_backend(self, envelope: InputEnvelope) -> str:
        kind = resolve_backend_from_target(envelope.target, self.sdk_targets, self.app_targets)
        if kind == "none":
            kind = self.args.default_backend
        if kind not in {"sdk", "app"}:
            raise ValueError(f"cannot resolve backend for target={envelope.target!r}")
        return kind

    def submit(self, envelope: InputEnvelope) -> None:
        backend_kind = self._resolve_backend(envelope)
        backend = self._get_backend(backend_kind)

        source_ai = envelope.target or f"{self.args.ai}_{backend_kind}"
        if self.args.emit_input_events:
            self._emit_event(
                event_type="input",
                text=envelope.message,
                task_id=envelope.task_id,
                source=envelope.source,
                source_ai=source_ai,
                backend=backend_kind,
                target=envelope.target,
            )

        output = backend.run_turn(envelope)
        self._emit_event(
            event_type="output",
            text=output,
            task_id=envelope.task_id,
            source=f"codex_{backend_kind}",
            source_ai=source_ai,
            backend=backend_kind,
            target=envelope.target,
        )

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
                envelope = parse_input_envelope(data.decode("utf-8", errors="replace"))
                if not envelope:
                    conn.sendall(b"ERR:invalid payload")
                    return
                self.submit(envelope)
                conn.sendall(b"OK")
            except Exception as exc:
                self._emit_event(
                    event_type="worker_error",
                    text=str(exc),
                    task_id=None,
                    source="worker",
                    source_ai=self.args.ai,
                    backend=None,
                    target=None,
                )
                conn.sendall(f"ERR:{exc}".encode("utf-8", errors="replace"))

    def serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.args.host, self.args.port))
            server.listen(self.args.backlog)
            print(
                f"[codex-agent-worker:{self.args.ai}] listening on {self.args.host}:{self.args.port} "
                f"sdk_targets={sorted(self.sdk_targets)} app_targets={sorted(self.app_targets)}"
            )
            try:
                while True:
                    conn, _ = server.accept()
                    threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
            except KeyboardInterrupt:
                pass
            finally:
                self.shutdown.set()
                self.emitter.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Codex agent worker (sdk/app-server alternative backend)")
    p.add_argument("--ai", default="codex")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9013)
    p.add_argument("--backlog", type=int, default=64)

    p.add_argument("--sdk-targets", default="codex_sdk")
    p.add_argument("--app-targets", default="codex_app")
    p.add_argument("--default-backend", choices=["sdk", "app", "none"], default="sdk")

    p.add_argument("--sdk-provider", choices=["mock", "subprocess"], default="mock")
    p.add_argument("--app-provider", choices=["mock", "subprocess", "app_server"], default="mock")
    p.add_argument("--sdk-command", default="")
    p.add_argument("--app-command", default="")
    p.add_argument("--backend-timeout-sec", type=float, default=45.0)

    p.add_argument("--app-server-url", default="")
    p.add_argument("--app-server-timeout-sec", type=float, default=20.0)
    p.add_argument("--app-resume-thread-id", default="")
    p.add_argument("--app-initialize-method", default="initialize")
    p.add_argument("--app-thread-start-method", default="thread/start")
    p.add_argument("--app-thread-resume-method", default="thread/resume")
    p.add_argument("--app-turn-start-method", default="turn/start")

    p.add_argument("--feedback-mode", choices=["ai_feedback", "file", "stdout"], default="ai_feedback")
    p.add_argument("--feedback-channel", choices=["db", "redis", "ask"], default="db")
    p.add_argument("--feedback-file", default="")
    p.add_argument("--python-exe", default=sys.executable)
    p.add_argument("--ai-feedback-path", default="ai_feedback.py")
    p.add_argument("--emit-input-events", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    worker = CodexAgentWorker(args)
    worker.serve()


if __name__ == "__main__":
    main()
