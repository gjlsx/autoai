#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
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
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            sock.close()
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


def insert_task(cfg: Dict[str, str], target: str, message: str) -> int:
    conn = mysql_connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_tasks (ai_target, message, status, priority, source_channel, source_chat_id, source_user_id, updated_at) "
                "VALUES (%s, %s, 'pending', 0, 'codex_agent_e2e', NULL, NULL, NOW())",
                (target, message),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def task_status(cfg: Dict[str, str], task_id: int) -> str:
    conn = mysql_connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM ai_tasks WHERE id=%s", (task_id,))
            row = cur.fetchone() or {}
            return str(row.get("status") or "")
    finally:
        conn.close()


def has_feedback(cfg: Dict[str, str], task_id: int, expected: str) -> bool:
    conn = mysql_connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM ai_feedback WHERE task_id=%s ORDER BY id DESC LIMIT 30", (str(task_id),))
            rows = cur.fetchall()
        for row in rows:
            payload = str(row.get("payload") or "")
            if expected in payload:
                return True
        return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end smoke: dispatcher -> codex_agent_worker -> ai_feedback(db)")
    parser.add_argument("--port", type=int, default=9923)
    parser.add_argument("--timeout-sec", type=int, default=80)
    args = parser.parse_args()

    cfg = parse_project_env(REPO_ROOT / ".env")
    env = os.environ.copy()
    env.update(cfg)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    runtime_dir = REPO_ROOT / ".runtime"
    worker_proc: Optional[subprocess.Popen] = None
    dispatcher_proc: Optional[subprocess.Popen] = None

    sdk_message = f"sdk-smoke-{run_id}"
    app_message = f"app-smoke-{run_id}"

    try:
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "one_click.py"), "stop"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        worker_proc = start_proc(
            [
                sys.executable,
                "-u",
                "codex_agent_worker.py",
                "--ai",
                "codex",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--sdk-provider",
                "mock",
                "--app-provider",
                "mock",
                "--sdk-targets",
                "codex_sdk",
                "--app-targets",
                "codex_app",
                "--feedback-mode",
                "ai_feedback",
                "--feedback-channel",
                "db",
                "--python-exe",
                sys.executable,
                "--emit-input-events",
            ],
            env,
            runtime_dir / f"e2e_codex_agent_worker.{run_id}.out.log",
            runtime_dir / f"e2e_codex_agent_worker.{run_id}.err.log",
        )

        if not wait_port(args.port, timeout_sec=8):
            print(f"[e2e-codex-agent] FAIL: worker not listening on {args.port}")
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
                f"codex_sdk={args.port},codex_app={args.port}",
            ],
            env,
            runtime_dir / f"e2e_codex_agent_dispatcher.{run_id}.out.log",
            runtime_dir / f"e2e_codex_agent_dispatcher.{run_id}.err.log",
        )

        sdk_task_id = insert_task(cfg, "codex_sdk", sdk_message)
        app_task_id = insert_task(cfg, "codex_app", app_message)
        print(f"[e2e-codex-agent] inserted sdk_task_id={sdk_task_id}, app_task_id={app_task_id}")

        deadline = time.time() + max(args.timeout_sec, 10)
        sdk_dispatched = False
        app_dispatched = False
        sdk_feedback = False
        app_feedback = False

        while time.time() < deadline:
            if not sdk_dispatched:
                sdk_dispatched = task_status(cfg, sdk_task_id) == "dispatched"
            if not app_dispatched:
                app_dispatched = task_status(cfg, app_task_id) == "dispatched"
            if not sdk_feedback:
                sdk_feedback = has_feedback(cfg, sdk_task_id, f"MOCK_SDK_REPLY:{sdk_message}")
            if not app_feedback:
                app_feedback = has_feedback(cfg, app_task_id, f"MOCK_APP_REPLY:{app_message}")

            if sdk_dispatched and app_dispatched and sdk_feedback and app_feedback:
                break
            time.sleep(0.5)

        if not sdk_dispatched:
            print(f"[e2e-codex-agent] FAIL: sdk task {sdk_task_id} not dispatched")
            return 1
        if not app_dispatched:
            print(f"[e2e-codex-agent] FAIL: app task {app_task_id} not dispatched")
            return 1
        if not sdk_feedback:
            print(f"[e2e-codex-agent] FAIL: sdk feedback missing for task {sdk_task_id}")
            return 1
        if not app_feedback:
            print(f"[e2e-codex-agent] FAIL: app feedback missing for task {app_task_id}")
            return 1

        print(
            "[e2e-codex-agent] PASS: "
            f"sdk_task={sdk_task_id}, app_task={app_task_id}, worker_port={args.port}"
        )
        return 0
    finally:
        terminate_proc(dispatcher_proc)
        terminate_proc(worker_proc)


if __name__ == "__main__":
    raise SystemExit(main())
