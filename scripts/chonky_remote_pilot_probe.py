#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


def _http_post_json(url: str, body: Dict[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def evaluate_repo(repo_path: Path) -> Dict[str, Any]:
    ext_ts = _load_text(repo_path / "src" / "extension.ts")
    tool_ts = _load_text(repo_path / "src" / "tools" / "remoteChat.ts")

    checks = {
        "repo_exists": repo_path.exists(),
        "register_tool": "registerTool('chonky_remotepilot'" in ext_ts,
        "wait_for_message": "transportManager.waitForMessage" in tool_ts,
        "send_message": "transportManager.sendMessage" in tool_ts,
        "loop_instruction": "MUST call chonky_remotepilot again" in tool_ts,
    }
    checks["supports_input_output_via_tool"] = bool(
        checks["register_tool"] and checks["wait_for_message"] and checks["send_message"]
    )
    return checks


def evaluate_runtime(rest_url: str, timeout: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "rest_reachable": False,
        "commands_total": 0,
        "chonky_commands": [],
        "vscode_chat_commands": [],
        "error": "",
    }
    try:
        commands = _http_post_json(rest_url, {"command": "custom.getCommands"}, timeout=timeout)
    except urllib.error.URLError as exc:
        out["error"] = f"rest_unreachable: {exc}"
        return out
    except Exception as exc:
        out["error"] = f"rest_error: {exc}"
        return out

    if not isinstance(commands, list):
        out["error"] = f"unexpected_command_list_type: {type(commands).__name__}"
        out["rest_reachable"] = True
        return out

    out["rest_reachable"] = True
    out["commands_total"] = len(commands)
    out["chonky_commands"] = [str(c) for c in commands if "chonky" in str(c).lower()]
    out["vscode_chat_commands"] = [
        str(c)
        for c in commands
        if str(c) in {"chatgpt.sidebarView.focus", "workbench.action.chat.focusInput", "workbench.action.chat.submit"}
    ]
    return out


def decide(repo_eval: Dict[str, Any], runtime_eval: Dict[str, Any]) -> Dict[str, Any]:
    chonky_runtime_ready = runtime_eval.get("rest_reachable") and bool(runtime_eval.get("chonky_commands"))
    static_tool_ready = bool(repo_eval.get("supports_input_output_via_tool"))

    # Current pipeline requirement: local worker needs deterministic message in/out extraction.
    # Chonky is a VSCode LanguageModelTool bridge; it is viable only if extension is enabled in active VSCode
    # and the chat agent actually calls the tool on each turn.
    usable = bool(chonky_runtime_ready and static_tool_ready)
    reasons: List[str] = []
    if not static_tool_ready:
        reasons.append("repo_static_check_failed")
    if not runtime_eval.get("rest_reachable"):
        reasons.append("rest_not_reachable")
    if runtime_eval.get("rest_reachable") and not runtime_eval.get("chonky_commands"):
        reasons.append("chonky_extension_not_active_in_current_vscode")
    if usable:
        reasons.append("chonky_path_can_be_tested_for_i_o")
    else:
        reasons.append("fallback_to_task2_recommended")

    return {"usable_for_current_pipeline": usable, "reasons": reasons}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Probe if vscode-chonky-remote-pilot can be used for Codex I/O path")
    p.add_argument("--repo-path", default=str(Path(".runtime") / "third_party" / "vscode-chonky-remote-pilot"))
    p.add_argument("--rest-url", default="http://127.0.0.1:49818")
    p.add_argument("--timeout-sec", type=float, default=10.0)
    p.add_argument("--output-json", default="")
    return p


def main() -> int:
    args = build_parser().parse_args()
    repo_path = Path(args.repo_path).resolve()

    repo_eval = evaluate_repo(repo_path)
    runtime_eval = evaluate_runtime(args.rest_url, timeout=args.timeout_sec)
    decision = decide(repo_eval, runtime_eval)

    report = {
        "repo_path": str(repo_path),
        "rest_url": args.rest_url,
        "repo_eval": repo_eval,
        "runtime_eval": runtime_eval,
        "decision": decision,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output_json:
        out_path = Path(args.output_json).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    return 0 if decision["usable_for_current_pipeline"] else 2


if __name__ == "__main__":
    sys.exit(main())

