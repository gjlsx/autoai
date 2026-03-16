from __future__ import annotations

import argparse
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import pymysql


@dataclass
class InputEnvelope:
    message: str
    task_id: Optional[str] = None
    target: Optional[str] = None
    source: str = "socket"
    sessionid: Optional[str] = None
    source_chat_id: Optional[str] = None
    source_user_id: Optional[str] = None
    meta: Dict[str, str] = field(default_factory=dict)


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
        source = str(data.get("source") or "socket").strip() or "socket"
        sessionid = data.get("sessionid")
        source_chat_id = data.get("source_chat_id")
        source_user_id = data.get("source_user_id")
        meta = {
            k: str(v)
            for k, v in data.items()
            if k
            not in {
                "message",
                "prompt",
                "input",
                "task_id",
                "id",
                "target",
                "source",
                "sessionid",
                "source_chat_id",
                "source_user_id",
            }
        }
        return InputEnvelope(
            message=message,
            task_id=str(task_id) if task_id is not None else None,
            target=str(target).strip().lower() if target is not None else None,
            source=source,
            sessionid=str(sessionid).strip() if sessionid is not None else None,
            source_chat_id=str(source_chat_id).strip() if source_chat_id is not None else None,
            source_user_id=str(source_user_id).strip() if source_user_id is not None else None,
            meta=meta,
        )

    return InputEnvelope(message=payload, source="socket")


def resolve_sessionid(ai: str, envelope: InputEnvelope) -> str:
    if envelope.sessionid and envelope.sessionid.strip():
        return envelope.sessionid.strip()[:77]
    base = (
        (envelope.source_chat_id or "").strip()
        or (envelope.source_user_id or "").strip()
        or (envelope.task_id or "").strip()
        or "default"
    )
    return f"{ai}:{base}"[:77]


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_incremental_text(previous: str, current: str) -> str:
    prev = _normalize_text(previous or "")
    curr = _normalize_text(current or "")
    if not curr:
        return ""
    if not prev:
        return curr.strip()
    if curr.startswith(prev):
        return curr[len(prev) :].strip()

    common = 0
    max_len = min(len(prev), len(curr))
    while common < max_len and prev[common] == curr[common]:
        common += 1
    return curr[common:].strip()


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def detect_codex_log_error(log_tail: str) -> Optional[str]:
    text = _normalize_text(log_tail or "")
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines[-200:]):
        lowered = line.lower()
        if "failed to apply patches for conversationid=" in lowered:
            return line
        if "codexmcpconnection" in lowered and "request failed" in lowered:
            return line
    return None


class RestCommandClient:
    def __init__(self, base_url: str, timeout_sec: float = 10.0):
        self.base_url = base_url
        self.timeout_sec = timeout_sec

    def execute(self, command: str, args: Optional[list[Any]] = None) -> Any:
        body: Dict[str, Any] = {"command": command}
        if args is not None:
            body["args"] = args
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} command={command}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"REST request failed command={command}: {exc}") from exc

        if raw == "":
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


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
                self._safe_stderr(f"[vscode-codex-worker] feedback emit error: {exc}")
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
                self._safe_stderr("[vscode-codex-worker] feedback-file is required when mode=file")
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
        sessionid = str(event.get("sessionid") or "").strip()
        if sessionid:
            cmd += ["--sessionid", sessionid]

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
            self._safe_stderr(f"[vscode-codex-worker] ai_feedback failed code={result.returncode} detail={detail}")


class StepFailed(RuntimeError):
    def __init__(self, step: str, retries: int, last_error: Exception):
        super().__init__(f"step={step} retries={retries} err={last_error}")
        self.step = step
        self.retries = retries
        self.last_error = last_error


class VscodeCodexWorker:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.shutdown = threading.Event()
        self.seq = 0
        self.seq_lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.emitter = FeedbackEmitter(args)
        self.rest = RestCommandClient(args.rest_url, timeout_sec=15.0)
        self.active_sessionid: Optional[str] = None

        self._mysql_lock = threading.RLock()
        self._mysql_conn = None
        self.command_profile = self._load_command_profile(args.command_profile)

    @staticmethod
    def _default_command_profile() -> Dict[str, Any]:
        return {
            "focus_commands": [
                "chatgpt.openSidebar",
                "chatgpt.sidebarView.open",
                "chatgpt.sidebarView.focus",
                "chat.action.focus",
                "workbench.action.chat.focusInput",
            ],
            "input_command_candidates": [
                "chatgpt.addToThread",
                "codex.addToThread",
                "chatgpt.ask",
            ],
            "copy_commands": [
                "workbench.action.chat.copyAll",
                "workbench.action.chat.copyItem",
            ],
            "copy_wait_ms": 300,
            "stream_fallback_output": True,
            "stream_fallback_text": "stream observed; response text copy unavailable",
        }

    def _load_command_profile(self, profile_path: str) -> Dict[str, Any]:
        profile = self._default_command_profile()
        if not profile_path:
            return profile
        path = Path(profile_path)
        if not path.is_absolute():
            path = (Path(__file__).resolve().parent / path).resolve()
        if not path.exists():
            return profile
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return profile
        if not isinstance(data, dict):
            return profile
        for k, v in data.items():
            profile[k] = v
        return profile

    def _emit_feedback_event(
        self,
        *,
        event_type: str,
        text: str,
        task_id: Optional[str],
        source: str,
        source_ai: Optional[str],
        sessionid: Optional[str],
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
            "sessionid": sessionid,
            "seq": seq,
            "ts": int(time.time()),
            "text": text,
        }
        self.emitter.emit(event)

    def _validate_identifier(self, value: str, field: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]+", value):
            raise ValueError(f"invalid {field}: {value}")

    def _get_mysql_conn(self):
        self._validate_identifier(self.args.mysql_db, "mysql_db")
        with self._mysql_lock:
            if self._mysql_conn is None:
                self._mysql_conn = pymysql.connect(
                    host=self.args.mysql_host,
                    port=self.args.mysql_port,
                    user=self.args.mysql_user,
                    password=self.args.mysql_password,
                    database=self.args.mysql_db,
                    autocommit=True,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                    connect_timeout=5,
                    read_timeout=15,
                    write_timeout=15,
                )
                return self._mysql_conn
            try:
                self._mysql_conn.ping(reconnect=True)
            except Exception:
                try:
                    self._mysql_conn.close()
                except Exception:
                    pass
                self._mysql_conn = pymysql.connect(
                    host=self.args.mysql_host,
                    port=self.args.mysql_port,
                    user=self.args.mysql_user,
                    password=self.args.mysql_password,
                    database=self.args.mysql_db,
                    autocommit=True,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                    connect_timeout=5,
                    read_timeout=15,
                    write_timeout=15,
                )
            return self._mysql_conn

    def _mark_task_failed(self, task_id: Optional[str], error: str) -> None:
        if not task_id:
            return
        try:
            conn = self._get_mysql_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_tasks SET status='failed', updated_at=NOW(), last_error=%s WHERE id=%s",
                    (error[:3000], str(task_id)),
                )
        except Exception:
            # best effort only
            return

    def _mark_task_status(self, task_id: Optional[str], status: str) -> None:
        if not task_id:
            return
        try:
            conn = self._get_mysql_conn()
            with conn.cursor() as cur:
                if status == "running":
                    cur.execute(
                        "UPDATE ai_tasks SET status='running', updated_at=NOW() "
                        "WHERE id=%s AND status IN ('pending','dispatching','dispatched','running')",
                        (str(task_id),),
                    )
                    return

                if status == "completed":
                    try:
                        cur.execute(
                            "UPDATE ai_tasks SET status='completed', updated_at=NOW(), finished_at=NOW(), last_error=NULL "
                            "WHERE id=%s",
                            (str(task_id),),
                        )
                    except pymysql.err.OperationalError as exc:
                        errno = None
                        if exc.args:
                            try:
                                errno = int(exc.args[0])
                            except Exception:
                                errno = None
                        if errno in {1054, 1136}:
                            cur.execute(
                                "UPDATE ai_tasks SET status='completed', updated_at=NOW(), last_error=NULL WHERE id=%s",
                                (str(task_id),),
                            )
                        else:
                            raise
                    return
        except Exception:
            # best effort only
            return

    def _insert_system_feedback(self, task_id: Optional[str], sessionid: Optional[str], payload: str) -> None:
        try:
            conn = self._get_mysql_conn()
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO ai_feedback (task_id, source_ai, channel, payload, sessionid) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (task_id, self.args.ai, "system", payload, sessionid),
                    )
                except pymysql.err.OperationalError as exc:
                    if exc.args and exc.args[0] in {1054, 1136}:
                        cur.execute(
                            "INSERT INTO ai_feedback (task_id, source_ai, channel, payload) "
                            "VALUES (%s, %s, %s, %s)",
                            (task_id, self.args.ai, "system", payload),
                        )
                    else:
                        raise
        except Exception:
            return

    def _emit_system_alert(
        self,
        *,
        task_id: Optional[str],
        sessionid: Optional[str],
        step: str,
        retries: int,
        last_error: str,
    ) -> None:
        payload = json.dumps(
            {
                "event": "system_alert",
                "ai": self.args.ai,
                "task_id": task_id,
                "sessionid": sessionid,
                "step": step,
                "retries": retries,
                "last_error": last_error,
                "ts": int(time.time()),
            },
            ensure_ascii=False,
        )
        self._insert_system_feedback(task_id=task_id, sessionid=sessionid, payload=payload)

    def _invoke_command(self, command: str, args: Optional[list[Any]] = None) -> Any:
        return self.rest.execute(command, args=args)

    def _run_step(self, step: str, command: str, args: Optional[list[Any]] = None) -> Any:
        last_exc: Optional[Exception] = None
        for _attempt in range(1, self.args.max_retries + 1):
            try:
                return self._invoke_command(command, args=args)
            except Exception as exc:
                last_exc = exc
                time.sleep(0.2)
        raise StepFailed(step=step, retries=self.args.max_retries, last_error=last_exc or RuntimeError("unknown"))

    def _read_window_state(self) -> Dict[str, Any]:
        expr = "JSON.stringify(vscode.window.state)"
        raw = self._run_step("read_window_state", "custom.eval", [expr])
        text = _to_text(raw).strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def _ensure_window_focused(self) -> None:
        if not getattr(self.args, "require_window_focused", True):
            return

        state = self._read_window_state()
        if bool(state.get("focused")):
            return

        focus_commands = self.command_profile.get("focus_commands") or []
        if isinstance(focus_commands, str):
            focus_commands = [focus_commands]
        last_state = state
        for _attempt in range(1, self.args.max_retries + 1):
            for idx, command in enumerate(focus_commands):
                if not command:
                    continue
                self._run_step(f"focus_retry_{idx}", str(command))
            time.sleep(0.2)
            state = self._read_window_state()
            last_state = state
            if bool(state.get("focused")):
                return

        raise StepFailed(
            step="window_focus",
            retries=self.args.max_retries,
            last_error=RuntimeError(f"vscode.window.state.focused=false state={last_state}"),
        )

    def _snapshot_chat_text(self) -> str:
        copy_commands = self.command_profile.get("copy_commands") or ["workbench.action.chat.copyAll"]
        if isinstance(copy_commands, str):
            copy_commands = [copy_commands]
        for idx, command in enumerate(copy_commands):
            if not command:
                continue
            self._run_step(f"copy_{idx}", str(command))
        wait_ms = int(self.command_profile.get("copy_wait_ms", 0) or 0)
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        text = self._run_step("read_clipboard", "custom.eval", ["vscode.env.clipboard.readText()"])
        return _normalize_text(_to_text(text))

    def _read_codex_log_length(self) -> int:
        expr = (
            "vscode.workspace.openTextDocument(vscode.Uri.parse('output:openai.chatgpt.Codex.log'))"
            ".then(doc=>doc.getText().length)"
        )
        value = self._run_step("read_codex_log_len", "custom.eval", [expr])
        try:
            return int(value)
        except Exception:
            return 0

    def _read_codex_log_tail(self, max_chars: int = 4000) -> str:
        expr = (
            "vscode.workspace.openTextDocument(vscode.Uri.parse('output:openai.chatgpt.Codex.log'))"
            f".then(doc=>doc.getText().slice(-{int(max_chars)}))"
        )
        value = self._run_step("read_codex_log_tail", "custom.eval", [expr])
        return _normalize_text(_to_text(value))

    def _ensure_session(self, sessionid: str) -> None:
        if self.active_sessionid == sessionid:
            return
        if self.active_sessionid is not None and getattr(self.args, "new_chat_on_session_change", False):
            self._run_step("new_chat", "chatgpt.newChat")
        self.active_sessionid = sessionid

    def _run_turn(self, *, message: str, sessionid: str) -> str:
        self._ensure_window_focused()
        baseline = self._snapshot_chat_text()
        last_log_tail = self._read_codex_log_tail()
        focus_commands = self.command_profile.get("focus_commands") or []
        if isinstance(focus_commands, str):
            focus_commands = [focus_commands]
        for idx, command in enumerate(focus_commands):
            if not command:
                continue
            self._run_step(f"focus_{idx}", str(command))

        resolved_commands = self._run_step("resolve_command", "custom.getCommands") or []
        if isinstance(resolved_commands, str):
            try:
                resolved_commands = json.loads(resolved_commands)
            except Exception:
                resolved_commands = []
        if not isinstance(resolved_commands, list):
            resolved_commands = []

        # Find best available command
        input_command_candidates = self.command_profile.get("input_command_candidates") or []
        
        send_cmd = None
        for candidate in input_command_candidates:
            if candidate in resolved_commands:
                send_cmd = candidate
                break
                
        if not send_cmd:
            raise StepFailed(
                step="resolve_command",
                retries=1,
                last_error=RuntimeError(f"No valid send command found in {resolved_commands}. Candidates: {input_command_candidates}")
            )
            
        self._run_step("send_input", send_cmd, [message])

        started = time.time()
        stream_seen = False
        last_stream_seen = started
        last_non_empty_delta = ""
        last_delta_at = started
        settle_window = max(0.5, self.args.poll_interval_sec * 3)
        stream_fallback_enabled = bool(self.command_profile.get("stream_fallback_output", True))
        stream_fallback_text = str(
            self.command_profile.get("stream_fallback_text") or "stream observed; response text copy unavailable"
        ).strip()
        while time.time() - started <= self.args.response_timeout_sec:
            current = self._snapshot_chat_text()
            delta = extract_incremental_text(baseline, current)
            if delta:
                now = time.time()
                if delta != last_non_empty_delta:
                    last_non_empty_delta = delta
                    last_delta_at = now
                elif (now - last_delta_at) >= settle_window:
                    return delta
            elif last_non_empty_delta and (time.time() - last_delta_at) >= settle_window:
                return last_non_empty_delta

            tail = self._read_codex_log_tail()
            if tail and tail != last_log_tail:
                last_log_tail = tail
                log_error = detect_codex_log_error(tail)
                if log_error:
                    raise StepFailed(
                        step="codex_log_error",
                        retries=self.args.max_retries,
                        last_error=RuntimeError(log_error),
                    )
                if "thread-stream-state-changed" in tail:
                    stream_seen = True
                    last_stream_seen = time.time()
            # No submit fallback logic anymore, since we inject directly via command now
            if stream_seen and (time.time() - last_stream_seen) >= max(2.0, self.args.poll_interval_sec * 3):
                final_current = self._snapshot_chat_text()
                final_delta = extract_incremental_text(baseline, final_current)
                if final_delta:
                    return final_delta
                if last_non_empty_delta:
                    return last_non_empty_delta
                if stream_fallback_enabled:
                    return stream_fallback_text
                raise StepFailed(
                    step="collect_output",
                    retries=self.args.max_retries,
                    last_error=RuntimeError("stream ended but no textual delta"),
                )
            time.sleep(self.args.poll_interval_sec)

        if stream_seen and stream_fallback_enabled:
            return stream_fallback_text
        raise StepFailed(
            step="collect_output",
            retries=self.args.max_retries,
            last_error=TimeoutError(f"no clipboard delta in {self.args.response_timeout_sec}s"),
        )

    def handle_envelope(self, envelope: InputEnvelope) -> bool:
        sessionid = resolve_sessionid(self.args.ai, envelope)
        try:
            self._mark_task_status(envelope.task_id, "running")
            self._ensure_session(sessionid)
            if self.args.emit_input_events:
                self._emit_feedback_event(
                    event_type="input",
                    text=envelope.message,
                    task_id=envelope.task_id,
                    source=envelope.source,
                    source_ai=envelope.target or self.args.ai,
                    sessionid=sessionid,
                    target=envelope.target,
                )

            output = self._run_turn(message=envelope.message, sessionid=sessionid)
            self._emit_feedback_event(
                event_type="output",
                text=output,
                task_id=envelope.task_id,
                source="vscode",
                source_ai=envelope.target or self.args.ai,
                sessionid=sessionid,
                target=envelope.target,
            )
            self._mark_task_status(envelope.task_id, "completed")
            return True
        except StepFailed as exc:
            err = str(exc.last_error)
            self._emit_system_alert(
                task_id=envelope.task_id,
                sessionid=sessionid,
                step=exc.step,
                retries=exc.retries,
                last_error=err,
            )
            self._mark_task_failed(envelope.task_id, err)
            return False
        except Exception as exc:
            err = str(exc)
            self._emit_system_alert(
                task_id=envelope.task_id,
                sessionid=sessionid,
                step="unknown",
                retries=self.args.max_retries,
                last_error=err,
            )
            self._mark_task_failed(envelope.task_id, err)
            return False

    def _handle_conn(self, conn: socket.socket) -> None:
        envelope: Optional[InputEnvelope] = None
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
                conn.sendall(b"OK")
            except Exception as exc:
                conn.sendall(f"ERR:{exc}".encode("utf-8", errors="replace"))
                return

        if envelope is None:
            return
        with self.turn_lock:
            self.handle_envelope(envelope)

    def serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.args.host, self.args.port))
            server.listen(self.args.backlog)
            print(
                f"[vscode-codex-worker:{self.args.ai}] listening on {self.args.host}:{self.args.port}, "
                f"rest={self.args.rest_url}, retries={self.args.max_retries}"
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
                with self._mysql_lock:
                    if self._mysql_conn is not None:
                        try:
                            self._mysql_conn.close()
                        except Exception:
                            pass
                        self._mysql_conn = None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VSCode Codex worker via REST Control")
    p.add_argument("--ai", default="codex")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9003)
    p.add_argument("--backlog", type=int, default=64)
    p.add_argument("--rest-url", default="http://127.0.0.1:49818")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--response-timeout-sec", type=float, default=120.0)
    p.add_argument("--poll-interval-sec", type=float, default=1.0)
    p.add_argument("--command-profile", default=str(Path("config") / "vscode_codex_command_profile.json"))
    p.add_argument(
        "--require-window-focused",
        action="store_true",
        default=True,
        help="Require VSCode window to be focused before submitting; fail fast if not focused.",
    )
    p.add_argument(
        "--allow-background-window",
        action="store_true",
        help="Allow background (not focused) VSCode window, disabling focus precheck.",
    )
    p.add_argument(
        "--new-chat-on-session-change",
        action="store_true",
        help="If set, create a new chat thread when incoming sessionid changes.",
    )

    p.add_argument("--feedback-mode", choices=["ai_feedback", "file", "stdout"], default="ai_feedback")
    p.add_argument("--feedback-channel", choices=["db", "redis", "ask"], default="db")
    p.add_argument("--feedback-file", default="")
    p.add_argument("--python-exe", default=sys.executable)
    p.add_argument("--ai-feedback-path", default="ai_feedback.py")
    p.add_argument("--emit-input-events", action="store_true")

    p.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    p.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    p.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    p.add_argument("--mysql-db", default=os.getenv("MYSQL_DB", "autoai"))
    return p


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "allow_background_window", False):
        args.require_window_focused = False
    worker = VscodeCodexWorker(args)
    worker.serve()


if __name__ == "__main__":
    main()
