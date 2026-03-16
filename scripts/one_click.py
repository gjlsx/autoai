#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


STATE_FILE_REL = Path(".runtime") / "local_stack_state.json"
DEFAULT_VSCODE_REST_CONFIG_REL = Path("config") / "vscode_rest_targets.json"
DEFAULT_ROUTING = "claude=9001,gemini=9002,codex=9003"
DEFAULT_CODEX_AGENT_PORT = 9013
PID_KEYS = (
    "bridge_codex_pid",
    "bridge_claude_pid",
    "bridge_gemini_pid",
    "codex_agent_pid",
    "dispatcher_pid",
)


def is_windows() -> bool:
    return os.name == "nt"


def default_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_repo_root(raw: str) -> Path:
    if raw:
        return Path(raw).resolve()
    return default_repo_root()


def strip_wrapping_quotes(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
        return value[1:-1]
    return value


def parse_project_env(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        raise RuntimeError(f".env not found: {env_path}")

    text = env_path.read_text(encoding="utf-8")

    def pick(name: str) -> str:
        m = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", text)
        if not m:
            return ""
        return strip_wrapping_quotes(m.group(1))

    mysql_host = pick("MYSQL_HOST")
    mysql_port = pick("MYSQL_PORT")
    mysql_user = pick("MYSQL_USER")
    mysql_password = pick("MYSQL_PASSWORD")
    mysql_db = pick("MYSQL_DB")

    if not mysql_host or not mysql_port:
        m_host = re.search(r"(?m)^\s*([A-Za-z0-9\.-]+)\s+(\d{2,5})\s*$", text)
        if m_host:
            mysql_host = mysql_host or m_host.group(1).strip()
            mysql_port = mysql_port or m_host.group(2).strip()

    if not mysql_user or not mysql_password:
        m_user = re.search(r"(?mi)^\s*([A-Za-z0-9_]+)\s+[^\r\n]*?pwd:\s*([^\s]+)\s*$", text)
        if m_user:
            mysql_user = mysql_user or m_user.group(1).strip()
            mysql_password = mysql_password or m_user.group(2).strip()

    if not mysql_db and mysql_user:
        m_db = re.match(r"^(.*)wr$", mysql_user)
        if m_db and m_db.group(1):
            mysql_db = m_db.group(1)

    if not all([mysql_host, mysql_port, mysql_user, mysql_password, mysql_db]):
        raise RuntimeError(
            "cannot parse mysql config from .env, please provide MYSQL_HOST/MYSQL_PORT/"
            "MYSQL_USER/MYSQL_PASSWORD/MYSQL_DB or legacy mysql note lines"
        )

    return {
        "MYSQL_HOST": mysql_host,
        "MYSQL_PORT": mysql_port,
        "MYSQL_USER": mysql_user,
        "MYSQL_PASSWORD": mysql_password,
        "MYSQL_DB": mysql_db,
    }


def parse_routing_map(raw: str) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, port = item.split("=", 1)
        name = name.strip().lower()
        if not name:
            continue
        mapping[name] = int(port.strip())
    return mapping


def routing_map_to_text(mapping: Dict[str, int]) -> str:
    return ",".join(f"{name}={port}" for name, port in mapping.items())


def parse_target_names(raw: str) -> set[str]:
    return {item.strip().lower() for item in (raw or "").split(",") if item.strip()}


def parse_vscode_rest_map(raw: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, url = item.split("=", 1)
        target = name.strip().lower()
        rest_url = url.strip()
        if not target or not rest_url:
            continue
        mapping[target] = rest_url
    return mapping


def load_vscode_worker_specs(
    *,
    repo_root: Path,
    default_rest_url: str,
    default_routing: Dict[str, int],
    config_rel_path: str,
    raw_rest_map: str,
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []

    config_path = (repo_root / config_rel_path).resolve()
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        workers = data.get("workers") if isinstance(data, dict) else None
        if isinstance(workers, list):
            for item in workers:
                if not isinstance(item, dict):
                    continue
                target = str(item.get("target") or "").strip().lower()
                if not target:
                    continue
                rest_url = str(item.get("rest_url") or "").strip()
                if not rest_url:
                    continue
                port_value = item.get("port")
                port = int(port_value) if isinstance(port_value, (int, str)) and str(port_value).strip() else 0
                specs.append(
                    {
                        "target": target,
                        "rest_url": rest_url,
                        "port": port,
                    }
                )

    cli_map = parse_vscode_rest_map(raw_rest_map)
    if cli_map:
        for target, rest_url in cli_map.items():
            updated = False
            for item in specs:
                if str(item.get("target")) == target:
                    item["rest_url"] = rest_url
                    updated = True
                    break
            if not updated:
                specs.append({"target": target, "rest_url": rest_url, "port": 0})

    if not specs:
        specs = [{"target": "codex", "rest_url": default_rest_url, "port": int(default_routing.get("codex", 9003))}]

    next_port = 9003
    for item in specs:
        target = str(item.get("target") or "").strip().lower()
        if not target:
            continue
        existing = int(default_routing.get(target, 0) or 0)
        configured = int(item.get("port", 0) or 0)
        if configured > 0:
            port = configured
        elif existing > 0:
            port = existing
        else:
            while next_port in default_routing.values():
                next_port += 1
            port = next_port
            next_port += 1
        item["port"] = int(port)
    return specs


def compose_routing_with_codex_agent(
    raw_routing: str,
    *,
    enable_codex_agent: bool,
    codex_agent_port: int,
    sdk_targets: set[str],
    app_targets: set[str],
) -> str:
    mapping = parse_routing_map(raw_routing)
    if not mapping:
        mapping = parse_routing_map(DEFAULT_ROUTING)
    if not enable_codex_agent:
        return routing_map_to_text(mapping)

    for name in sorted(sdk_targets | app_targets):
        if name not in mapping:
            mapping[name] = codex_agent_port
    return routing_map_to_text(mapping)


def load_state(state_path: Path) -> Dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state_path: Path, state: Dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if is_windows():
        cmd = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = res.stdout.strip()
        if not output or "No tasks are running" in output:
            return False
        return str(pid) in output
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_name(pid: int) -> str:
    if pid <= 0:
        return ""
    if is_windows():
        cmd = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        raw = res.stdout.strip()
        if not raw or "No tasks are running" in raw:
            return ""
        try:
            row = next(csv.reader([raw]))
        except Exception:
            return ""
        if len(row) >= 1:
            return row[0].strip().lower()
        return ""
    cmd = ["ps", "-p", str(pid), "-o", "comm="]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.stdout.strip().lower()


def kill_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    if is_windows():
        cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return res.returncode == 0

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    return not pid_alive(pid)


def list_python_processes() -> List[Tuple[int, str]]:
    rows: List[Tuple[int, str]] = []
    if is_windows():
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter "
            "\"name='python.exe' OR name='pythonw.exe'\" | "
            "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode != 0 or not res.stdout.strip():
            return rows
        try:
            data = json.loads(res.stdout)
        except Exception:
            return rows
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return rows
        for item in data:
            if not isinstance(item, dict):
                continue
            pid = int(item.get("ProcessId", 0) or 0)
            cmd = str(item.get("CommandLine") or "")
            if pid > 0:
                rows.append((pid, cmd))
        return rows

    res = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return rows
    for line in res.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        pid_raw, cmd = parts
        if not pid_raw.isdigit():
            continue
        if "python" not in cmd.lower():
            continue
        rows.append((int(pid_raw), cmd))
    return rows


def parse_pid_from_token(token: str) -> int:
    token = token.strip()
    if not token:
        return 0
    if token.isdigit():
        return int(token)
    m = re.match(r"^(\d+)", token)
    if not m:
        return 0
    return int(m.group(1))


def local_addr_matches_port(local_addr: str, port: int) -> bool:
    local_addr = local_addr.strip()
    if not local_addr:
        return False
    if local_addr.endswith(f":{port}"):
        return True
    if local_addr.endswith(f".{port}"):
        return True
    return False


def pids_listening_on_port(port: int) -> List[int]:
    pids: List[int] = []
    res = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return pids

    for line in res.stdout.splitlines():
        row = line.strip()
        if not row:
            continue
        parts = row.split()
        if is_windows():
            if len(parts) < 5:
                continue
            proto, local_addr, _, state, pid_token = parts[0], parts[1], parts[2], parts[3], parts[4]
            if proto.upper() != "TCP" or state.upper() != "LISTENING":
                continue
        else:
            if len(parts) < 7:
                continue
            proto, local_addr, state, pid_token = parts[0], parts[3], parts[5], parts[6]
            if not proto.lower().startswith("tcp") or state.upper() != "LISTEN":
                continue
        if not local_addr_matches_port(local_addr, port):
            continue
        pid = parse_pid_from_token(pid_token)
        if pid > 0:
            pids.append(pid)
    return sorted(set(pids))


def read_log_head(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[:max_lines]).strip()
    except Exception:
        return ""


def assert_process_alive(name: str, pid: int, out_log: Path, err_log: Path) -> None:
    time.sleep(0.4)
    if pid_alive(pid):
        return
    out_text = read_log_head(out_log, 20)
    err_text = read_log_head(err_log, 20)
    raise RuntimeError(
        f"process '{name}' pid={pid} exited early.\nerr:\n{err_text}\nout:\n{out_text}"
    )


def wait_for_port(port: int, timeout_sec: float = 3.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            sock.close()
        time.sleep(0.1)
    return False


def assert_bridge_listening(name: str, port: int, err_log: Path) -> None:
    if wait_for_port(port, timeout_sec=4.0):
        return
    err_text = read_log_head(err_log, 30)
    raise RuntimeError(f"bridge '{name}' not listening on 127.0.0.1:{port}\nerr:\n{err_text}")


def build_process_env(extra: Dict[str, str] | None = None) -> Dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    return env


def start_process(
    *,
    name: str,
    python_exe: str,
    proc_args: Sequence[str],
    repo_root: Path,
    runtime_dir: Path,
    run_id: str,
    dry_run: bool,
    extra_env: Dict[str, str] | None = None,
) -> Dict[str, object]:
    out_log = runtime_dir / f"{name}.{run_id}.out.log"
    err_log = runtime_dir / f"{name}.{run_id}.err.log"
    if dry_run:
        print(f"[dry-run] {python_exe} {' '.join(shlex.quote(x) for x in proc_args)}")
        if extra_env:
            print(f"[dry-run] env keys: {', '.join(sorted(extra_env.keys()))}")
        return {"pid": 0, "out_log": str(out_log), "err_log": str(err_log)}

    out_fp = out_log.open("w", encoding="utf-8", errors="replace")
    err_fp = err_log.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [python_exe, *proc_args],
            cwd=str(repo_root),
            stdout=out_fp,
            stderr=err_fp,
            env=build_process_env(extra_env),
        )
    finally:
        out_fp.close()
        err_fp.close()

    return {"pid": int(proc.pid), "out_log": str(out_log), "err_log": str(err_log)}


def stop_stack(repo_root: Path, state_path: Path, ports: Iterable[int]) -> List[str]:
    killed: List[str] = []
    killed_pids = set()

    state = load_state(state_path)
    for key in PID_KEYS:
        pid = int(state.get(key, 0) or 0)
        if pid <= 0:
            continue
        if kill_pid(pid):
            killed.append(f"{key}={pid}")
            killed_pids.add(pid)

    repo_marker = str(repo_root).lower().replace("\\", "/")
    for pid, cmd in list_python_processes():
        cmd_norm = cmd.lower().replace("\\", "/")
        if pid in killed_pids:
            continue
        if repo_marker and repo_marker not in cmd_norm:
            continue
        if (
            "window_bridge.py" not in cmd_norm
            and "pty_worker.py" not in cmd_norm
            and "vscode_codex_worker.py" not in cmd_norm
            and "codex_agent_worker.py" not in cmd_norm
            and "dispatcher.py" not in cmd_norm
        ):
            continue
        if kill_pid(pid):
            killed.append(f"proc={pid}")
            killed_pids.add(pid)

    for port in ports:
        for pid in pids_listening_on_port(port):
            if pid in killed_pids:
                continue
            pname = process_name(pid)
            if "python" not in pname:
                continue
            if kill_pid(pid):
                killed.append(f"port{port}_pid={pid}")
                killed_pids.add(pid)

    if state_path.exists():
        state_path.unlink()
    return killed


def build_bridge_or_worker_args(
    args: argparse.Namespace,
    *,
    ai: str,
    port: int,
    cli: str,
    python_exe: str,
    vscode_rest_url: str | None = None,
    use_vscode_worker: bool = False,
) -> List[str]:
    if use_vscode_worker or ai == "codex":
        rest_url = vscode_rest_url or args.vscode_rest_url
        proc_args = [
            "-u",
            "vscode_codex_worker.py",
            "--ai",
            ai,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--rest-url",
            rest_url,
            "--max-retries",
            str(args.vscode_max_retries),
            "--response-timeout-sec",
            str(args.vscode_response_timeout_sec),
            "--poll-interval-sec",
            str(args.vscode_poll_interval_sec),
            "--command-profile",
            args.vscode_command_profile,
            "--feedback-mode",
            args.pty_feedback_mode,
            "--feedback-channel",
            args.pty_feedback_channel,
            "--python-exe",
            python_exe,
        ]
        if args.vscode_new_chat_on_session_change:
            proc_args.append("--new-chat-on-session-change")
        if args.pty_feedback_mode == "file" and args.pty_feedback_file:
            proc_args.extend(["--feedback-file", args.pty_feedback_file])
        if args.pty_emit_input_events:
            proc_args.append("--emit-input-events")
        return proc_args

    if args.bridge_mode == "window":
        return ["-u", "window_bridge.py", "--ai", ai, "--port", str(port), "--cli", cli]

    proc_args = [
        "-u",
        "pty_worker.py",
        "--ai",
        ai,
        "--port",
        str(port),
        "--cli",
        cli,
        "--feedback-mode",
        args.pty_feedback_mode,
        "--feedback-channel",
        args.pty_feedback_channel,
        "--python-exe",
        python_exe,
        "--pywinpty-backend",
        args.pty_backend,
    ]
    if args.pty_feedback_mode == "file" and args.pty_feedback_file:
        proc_args.extend(["--feedback-file", args.pty_feedback_file])
    if args.pty_emit_input_events:
        proc_args.append("--emit-input-events")
    return proc_args


def build_codex_agent_args(args: argparse.Namespace, *, python_exe: str) -> List[str]:
    proc_args = [
        "-u",
        "codex_agent_worker.py",
        "--ai",
        "codex",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.codex_agent_port),
        "--sdk-targets",
        args.codex_agent_sdk_targets,
        "--app-targets",
        args.codex_agent_app_targets,
        "--default-backend",
        args.codex_agent_default_backend,
        "--sdk-provider",
        args.codex_sdk_provider,
        "--app-provider",
        args.codex_app_provider,
        "--feedback-mode",
        args.pty_feedback_mode,
        "--feedback-channel",
        args.pty_feedback_channel,
        "--python-exe",
        python_exe,
    ]
    if args.codex_sdk_command:
        proc_args.extend(["--sdk-command", args.codex_sdk_command])
    if args.codex_app_command:
        proc_args.extend(["--app-command", args.codex_app_command])
    if args.codex_agent_app_server_url:
        proc_args.extend(["--app-server-url", args.codex_agent_app_server_url])
    if args.codex_agent_app_resume_thread_id:
        proc_args.extend(["--app-resume-thread-id", args.codex_agent_app_resume_thread_id])
    if args.pty_feedback_mode == "file" and args.pty_feedback_file:
        proc_args.extend(["--feedback-file", args.pty_feedback_file])
    if args.pty_emit_input_events:
        proc_args.append("--emit-input-events")
    return proc_args


def cmd_start(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo_root)
    runtime_dir = repo_root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = repo_root / STATE_FILE_REL
    env_path = repo_root / ".env"
    run_id = time.strftime("%Y%m%d-%H%M%S")
    python_exe = args.python_exe or sys.executable or "python"
    sdk_targets = parse_target_names(args.codex_agent_sdk_targets)
    app_targets = parse_target_names(args.codex_agent_app_targets)
    routing_seed = compose_routing_with_codex_agent(
        args.routing,
        enable_codex_agent=args.start_codex_agent,
        codex_agent_port=args.codex_agent_port,
        sdk_targets=sdk_targets,
        app_targets=app_targets,
    )
    routing_map = parse_routing_map(routing_seed)
    if not routing_map:
        routing_map = parse_routing_map(DEFAULT_ROUTING)

    vscode_workers = load_vscode_worker_specs(
        repo_root=repo_root,
        default_rest_url=args.vscode_rest_url,
        default_routing=routing_map,
        config_rel_path=args.vscode_rest_config,
        raw_rest_map=args.vscode_rest_map,
    )
    for spec in vscode_workers:
        routing_map[str(spec["target"])] = int(spec["port"])
    routing_effective = routing_map_to_text(routing_map)

    ports = [int(spec["port"]) for spec in vscode_workers]
    if args.start_claude:
        ports.append(9001)
    if args.start_gemini:
        ports.append(9002)
    if args.start_codex_agent:
        ports.append(int(args.codex_agent_port))

    if args.dry_run:
        print("[dry-run] skip stopping existing processes")
    else:
        old = stop_stack(repo_root, state_path, ports)
        if old:
            print("Stopped old processes: " + ", ".join(old))

    mysql_cfg = parse_project_env(env_path)
    if args.dry_run:
        print(
            "[dry-run] mysql="
            + f"{mysql_cfg['MYSQL_USER']}@{mysql_cfg['MYSQL_HOST']}:{mysql_cfg['MYSQL_PORT']}/{mysql_cfg['MYSQL_DB']}"
        )
        print(f"[dry-run] routing_effective={routing_effective}")

    state: Dict[str, object] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_id": run_id,
        "bridge_mode": args.bridge_mode,
        "codex_path": "vscode_rest_control",
        "routing": routing_effective,
        "mysql_host": mysql_cfg["MYSQL_HOST"],
        "mysql_port": int(mysql_cfg["MYSQL_PORT"]),
        "mysql_user": mysql_cfg["MYSQL_USER"],
        "mysql_db": mysql_cfg["MYSQL_DB"],
    }

    started_workers: List[Dict[str, Any]] = []
    for spec in vscode_workers:
        target = str(spec["target"])
        port = int(spec["port"])
        rest_url = str(spec["rest_url"])
        name = f"bridge_{target}"
        bridge = start_process(
            name=name,
            python_exe=python_exe,
            proc_args=build_bridge_or_worker_args(
                args,
                ai=target,
                port=port,
                cli=args.codex_cli,
                python_exe=python_exe,
                vscode_rest_url=rest_url,
                use_vscode_worker=True,
            ),
            repo_root=repo_root,
            runtime_dir=runtime_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            extra_env=mysql_cfg,
        )
        started_workers.append(
            {
                "target": target,
                "port": port,
                "rest_url": rest_url,
                "pid": int(bridge["pid"]),
                "out_log": str(bridge["out_log"]),
                "err_log": str(bridge["err_log"]),
            }
        )
        if target == "codex":
            state["bridge_codex_pid"] = bridge["pid"]
            state["bridge_codex_out_log"] = bridge["out_log"]
            state["bridge_codex_err_log"] = bridge["err_log"]
        if not args.dry_run:
            assert_process_alive(
                name,
                int(bridge["pid"]),
                Path(str(bridge["out_log"])),
                Path(str(bridge["err_log"])),
            )
            assert_bridge_listening(name, port, Path(str(bridge["err_log"])))
    state["vscode_workers"] = started_workers

    if args.start_claude:
        bridge_claude = start_process(
            name="bridge_claude",
            python_exe=python_exe,
            proc_args=build_bridge_or_worker_args(
                args,
                ai="claude",
                port=9001,
                cli=args.claude_cli,
                python_exe=python_exe,
            ),
            repo_root=repo_root,
            runtime_dir=runtime_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            extra_env=mysql_cfg if args.bridge_mode == "pty" else None,
        )
        state["bridge_claude_pid"] = bridge_claude["pid"]
        state["bridge_claude_out_log"] = bridge_claude["out_log"]
        state["bridge_claude_err_log"] = bridge_claude["err_log"]
        if not args.dry_run:
            assert_process_alive(
                "bridge_claude",
                int(bridge_claude["pid"]),
                Path(str(bridge_claude["out_log"])),
                Path(str(bridge_claude["err_log"])),
            )
            assert_bridge_listening("bridge_claude", 9001, Path(str(bridge_claude["err_log"])))

    if args.start_gemini:
        bridge_gemini = start_process(
            name="bridge_gemini",
            python_exe=python_exe,
            proc_args=build_bridge_or_worker_args(
                args,
                ai="gemini",
                port=9002,
                cli=args.gemini_cli,
                python_exe=python_exe,
            ),
            repo_root=repo_root,
            runtime_dir=runtime_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            extra_env=mysql_cfg if args.bridge_mode == "pty" else None,
        )
        state["bridge_gemini_pid"] = bridge_gemini["pid"]
        state["bridge_gemini_out_log"] = bridge_gemini["out_log"]
        state["bridge_gemini_err_log"] = bridge_gemini["err_log"]
        if not args.dry_run:
            assert_process_alive(
                "bridge_gemini",
                int(bridge_gemini["pid"]),
                Path(str(bridge_gemini["out_log"])),
                Path(str(bridge_gemini["err_log"])),
            )
            assert_bridge_listening("bridge_gemini", 9002, Path(str(bridge_gemini["err_log"])))

    if args.start_codex_agent:
        codex_agent = start_process(
            name="codex_agent",
            python_exe=python_exe,
            proc_args=build_codex_agent_args(args, python_exe=python_exe),
            repo_root=repo_root,
            runtime_dir=runtime_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            extra_env=mysql_cfg,
        )
        state["codex_agent_pid"] = codex_agent["pid"]
        state["codex_agent_out_log"] = codex_agent["out_log"]
        state["codex_agent_err_log"] = codex_agent["err_log"]
        if not args.dry_run:
            assert_process_alive(
                "codex_agent",
                int(codex_agent["pid"]),
                Path(str(codex_agent["out_log"])),
                Path(str(codex_agent["err_log"])),
            )
            assert_bridge_listening("codex_agent", int(args.codex_agent_port), Path(str(codex_agent["err_log"])))

    dispatcher = start_process(
        name="dispatcher",
        python_exe=python_exe,
        proc_args=[
            "-u",
            "dispatcher.py",
            "--disable-redis",
            "--enable-mysql",
            "--no-user-input",
            "--routing",
            routing_effective,
        ],
        repo_root=repo_root,
        runtime_dir=runtime_dir,
        run_id=run_id,
        dry_run=args.dry_run,
        extra_env=mysql_cfg,
    )
    state["dispatcher_pid"] = dispatcher["pid"]
    state["dispatcher_out_log"] = dispatcher["out_log"]
    state["dispatcher_err_log"] = dispatcher["err_log"]
    if not args.dry_run:
        assert_process_alive(
            "dispatcher",
            int(dispatcher["pid"]),
            Path(str(dispatcher["out_log"])),
            Path(str(dispatcher["err_log"])),
        )

    if args.dry_run:
        print("Dry-run complete.")
        return 0

    save_state(state_path, state)
    print("AutoAI local stack started.")
    print(f"state_file: {state_path}")
    print(f"logs_dir: {runtime_dir}")
    if started_workers:
        print("vscode_workers:")
        for item in started_workers:
            print(
                f"  - target={item['target']} port={item['port']} rest={item['rest_url']} pid={item['pid']}"
            )
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo_root)
    state_path = repo_root / STATE_FILE_REL
    killed = stop_stack(repo_root, state_path, ports=(9001, 9002, 9003, DEFAULT_CODEX_AGENT_PORT))
    if killed:
        print("Stopped: " + ", ".join(killed))
    else:
        print("No managed processes found.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo_root)
    state_path = repo_root / STATE_FILE_REL
    state = load_state(state_path)
    if not state:
        print(f"No state file found: {state_path}")
        return 0

    print(f"started_at: {state.get('started_at', '-')}")
    if state.get("bridge_mode"):
        print(f"bridge_mode: {state.get('bridge_mode')}")
    if state.get("routing"):
        print(f"routing: {state.get('routing')}")
    print(
        "mysql: "
        + f"{state.get('mysql_user', '-')}"
        + "@"
        + f"{state.get('mysql_host', '-')}:{state.get('mysql_port', '-')}"
        + "/"
        + f"{state.get('mysql_db', '-')}"
    )

    for key in PID_KEYS:
        pid = int(state.get(key, 0) or 0)
        if pid <= 0:
            continue
        if pid_alive(pid):
            print(f"[alive] {key}={pid}")
        else:
            print(f"[dead] {key}={pid}")

    print(f"logs: {repo_root / '.runtime'}")
    workers = state.get("vscode_workers")
    if isinstance(workers, list):
        for item in workers:
            if not isinstance(item, dict):
                continue
            pid = int(item.get("pid", 0) or 0)
            target = str(item.get("target", "-"))
            port = item.get("port", "-")
            rest = item.get("rest_url", "-")
            mark = "alive" if pid_alive(pid) else "dead"
            print(f"[{mark}] vscode_worker target={target} pid={pid} port={port} rest={rest}")
    for key in (
        "bridge_codex_out_log",
        "bridge_codex_err_log",
        "bridge_claude_out_log",
        "bridge_claude_err_log",
        "bridge_gemini_out_log",
        "bridge_gemini_err_log",
        "codex_agent_out_log",
        "codex_agent_err_log",
        "dispatcher_out_log",
        "dispatcher_err_log",
    ):
        if key in state:
            print(f"{key}: {state[key]}")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(args.repo_root)
    env_path = repo_root / ".env"
    mysql_cfg = parse_project_env(env_path)
    python_exe = args.python_exe or sys.executable or "python"
    cmd = [
        python_exe,
        "ai_feedback.py",
        "--source-ai",
        args.source_ai,
        "--task-id",
        str(args.task_id),
        "--db",
        args.message,
    ]
    if args.dry_run:
        print("[dry-run] " + " ".join(shlex.quote(x) for x in cmd))
        return 0

    res = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=build_process_env(mysql_cfg),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.stdout.strip():
        print(res.stdout.strip())
    if res.stderr.strip():
        print(res.stderr.strip())
    return int(res.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoAI one-click local stack manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="start local worker(s) + dispatcher")
    start.add_argument("--repo-root", default="", help="repo root path, default: auto-detect")
    start.add_argument("--python-exe", default=sys.executable or "python", help="python executable path")
    start.add_argument("--routing", default=DEFAULT_ROUTING)
    start.add_argument("--bridge-mode", choices=["pty", "window"], default="pty")
    start.add_argument("--codex-cli", default="codex")
    start.add_argument("--claude-cli", default="claude")
    start.add_argument("--gemini-cli", default="gemini")
    start.add_argument("--pty-backend", choices=["auto", "conpty", "winpty"], default="auto")
    start.add_argument("--pty-feedback-mode", choices=["ai_feedback", "file", "stdout"], default="ai_feedback")
    start.add_argument("--pty-feedback-channel", choices=["db", "redis", "ask"], default="db")
    start.add_argument("--pty-feedback-file", default="")
    start.add_argument("--pty-emit-input-events", action="store_true")
    start.add_argument("--vscode-rest-url", default="http://127.0.0.1:49818")
    start.add_argument("--vscode-rest-config", default=str(DEFAULT_VSCODE_REST_CONFIG_REL))
    start.add_argument(
        "--vscode-rest-map",
        default="",
        help="override mapping: target=url,target2=url2",
    )
    start.add_argument(
        "--vscode-command-profile",
        default=str(Path("config") / "vscode_codex_command_profile.json"),
        help="relative or absolute JSON profile path for vscode_codex_worker command pipeline",
    )
    start.add_argument("--vscode-max-retries", type=int, default=3)
    start.add_argument("--vscode-response-timeout-sec", type=float, default=120.0)
    start.add_argument("--vscode-poll-interval-sec", type=float, default=1.0)
    start.add_argument(
        "--vscode-new-chat-on-session-change",
        action="store_true",
        default=True,
        help="If set, create a new chat thread when incoming sessionid changes.",
    )
    start.add_argument("--start-codex-agent", dest="start_codex_agent", action="store_true")
    start.add_argument("--no-start-codex-agent", dest="start_codex_agent", action="store_false")
    start.add_argument("--codex-agent-port", type=int, default=DEFAULT_CODEX_AGENT_PORT)
    start.add_argument("--codex-agent-sdk-targets", default="codex_sdk")
    start.add_argument("--codex-agent-app-targets", default="codex_app")
    start.add_argument("--codex-agent-default-backend", choices=["sdk", "app", "none"], default="sdk")
    start.add_argument("--codex-sdk-provider", choices=["mock", "subprocess"], default="mock")
    start.add_argument("--codex-app-provider", choices=["mock", "subprocess", "app_server"], default="mock")
    start.add_argument("--codex-sdk-command", default="")
    start.add_argument("--codex-app-command", default="")
    start.add_argument("--codex-agent-app-server-url", default="")
    start.add_argument("--codex-agent-app-resume-thread-id", default="")
    start.add_argument("--start-claude", action="store_true", help="start claude bridge on 9001")
    start.add_argument("--start-gemini", action="store_true", help="start gemini bridge on 9002")
    start.add_argument("--dry-run", action="store_true")
    start.set_defaults(start_codex_agent=False)
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help="stop local bridges + dispatcher")
    stop.add_argument("--repo-root", default="", help="repo root path, default: auto-detect")
    stop.set_defaults(func=cmd_stop)

    status = subparsers.add_parser("status", help="show local stack status")
    status.add_argument("--repo-root", default="", help="repo root path, default: auto-detect")
    status.set_defaults(func=cmd_status)

    feedback = subparsers.add_parser("feedback", help="write one feedback row via ai_feedback.py")
    feedback.add_argument("--repo-root", default="", help="repo root path, default: auto-detect")
    feedback.add_argument("--python-exe", default=sys.executable or "python", help="python executable path")
    feedback.add_argument("--task-id", required=True)
    feedback.add_argument("--message", required=True)
    feedback.add_argument("--source-ai", default="codex")
    feedback.add_argument("--dry-run", action="store_true")
    feedback.set_defaults(func=cmd_feedback)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as exc:
        print(f"[one_click] error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
