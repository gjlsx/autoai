#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Optional

import pymysql


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.one_click import parse_project_env  # noqa: E402


def wait_port(port: int, timeout_sec: float = 8.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.1)
    return False


def mysql_connect(cfg: Dict[str, str]):
    return pymysql.connect(
        host=cfg["MYSQL_HOST"],
        port=int(cfg["MYSQL_PORT"]),
        user=cfg["MYSQL_USER"],
        password=cfg["MYSQL_PASSWORD"],
        database=cfg["MYSQL_DB"],
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def start_proc(cmd: list[str], env: Optional[dict], out_path: Path, err_path: Path) -> subprocess.Popen:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = out_path.open("w", encoding="utf-8", errors="replace")
    err = err_path.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=out,
            stderr=err,
        )
    finally:
        out.close()
        err.close()
    return proc


def terminate_proc(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end smoke: dispatcher -> pty_worker -> ai_feedback(db)")
    parser.add_argument("--timeout-sec", type=int, default=80)
    parser.add_argument("--port", type=int, default=9913)
    args = parser.parse_args()

    env_path = REPO_ROOT / ".env"
    cfg = parse_project_env(env_path)
    env = os.environ.copy()
    env.update(cfg)

    runtime_dir = REPO_ROOT / ".runtime"
    run_id = time.strftime("%Y%m%d-%H%M%S")
    port = args.port
    target_ai = "codex_e2e"
    probe_message = f"pty-e2e-{run_id}"
    pty_proc: Optional[subprocess.Popen] = None
    dispatcher_proc: Optional[subprocess.Popen] = None

    try:
        # Ensure there is no existing local dispatcher/bridge/worker interference.
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "one_click.py"), "stop"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        cli_cmd = subprocess.list2cmdline([sys.executable, str(REPO_ROOT / "scripts" / "mock_ai_cli.py")])
        pty_proc = start_proc(
            [
                sys.executable,
                "-u",
                "pty_worker.py",
                "--ai",
                "codex",
                "--cli",
                cli_cmd,
                "--port",
                str(port),
                "--feedback-mode",
                "ai_feedback",
                "--feedback-channel",
                "db",
                "--python-exe",
                sys.executable,
                "--max-event-delay-sec",
                "0.3",
                "--min-event-chars",
                "20",
                "--emit-input-events",
            ],
            env,
            runtime_dir / f"e2e_pty_worker.{run_id}.out.log",
            runtime_dir / f"e2e_pty_worker.{run_id}.err.log",
        )
        if not wait_port(port, timeout_sec=8):
            print("[e2e] FAIL: pty_worker did not listen on port", port)
            return 1

        dispatcher_proc = start_proc(
            [
                sys.executable,
                "-u",
                "dispatcher.py",
                "--disable-redis",
                "--enable-mysql",
                "--no-user-input",
                "--routing",
                f"{target_ai}={port}",
            ],
            env,
            runtime_dir / f"e2e_dispatcher.{run_id}.out.log",
            runtime_dir / f"e2e_dispatcher.{run_id}.err.log",
        )

        conn = mysql_connect(cfg)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_tasks (ai_target, message, status, priority, source_channel, source_chat_id, source_user_id, updated_at) "
                    "VALUES (%s, %s, 'pending', 0, 'pty_e2e', NULL, NULL, NOW())",
                    (target_ai, probe_message),
                )
                task_id = int(cur.lastrowid)
        finally:
            conn.close()

        print(f"[e2e] inserted task_id={task_id} message={probe_message}")

        deadline = time.time() + max(args.timeout_sec, 10)
        seen_dispatched = False
        seen_feedback = False
        seen_ai_output = False
        feedback_row_id = None
        while time.time() < deadline:
            conn = mysql_connect(cfg)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT status FROM ai_tasks WHERE id=%s", (task_id,))
                    row = cur.fetchone() or {}
                    status = str(row.get("status") or "")
                    if status == "dispatched":
                        seen_dispatched = True

                    cur.execute(
                        "SELECT id, payload FROM ai_feedback WHERE task_id=%s ORDER BY id DESC LIMIT 20",
                        (str(task_id),),
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        payload = str(r.get("payload") or "")
                        if probe_message in payload:
                            seen_feedback = True
                            feedback_row_id = int(r["id"])
                        if "MOCK_AI_ECHO:" + probe_message in payload:
                            seen_ai_output = True
                            feedback_row_id = int(r["id"])
                            break
            finally:
                conn.close()

            if seen_dispatched and seen_feedback and seen_ai_output:
                break
            time.sleep(0.5)

        if not seen_dispatched:
            print(f"[e2e] FAIL: task {task_id} not dispatched")
            return 1
        if not seen_feedback:
            print(f"[e2e] FAIL: no feedback payload captured for task {task_id}")
            return 1
        if not seen_ai_output:
            print(f"[e2e] FAIL: no AI output echo captured for task {task_id}")
            return 1

        print(f"[e2e] PASS: task={task_id} dispatched, feedback_id={feedback_row_id}")
        return 0
    finally:
        terminate_proc(dispatcher_proc)
        terminate_proc(pty_proc)


if __name__ == "__main__":
    raise SystemExit(main())
