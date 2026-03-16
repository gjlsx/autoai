import json
from argparse import Namespace
from pathlib import Path

from vscode_codex_worker import VscodeCodexWorker


def _args(tmp_path: Path, **overrides):
    base = dict(
        ai="codex",
        host="127.0.0.1",
        port=9103,
        backlog=64,
        rest_url="http://127.0.0.1:49818",
        max_retries=3,
        response_timeout_sec=5.0,
        poll_interval_sec=0.01,
        command_profile="",
        feedback_mode="file",
        feedback_channel="db",
        feedback_file=str(tmp_path / "events.jsonl"),
        python_exe="python",
        ai_feedback_path="ai_feedback.py",
        emit_input_events=False,
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="pw",
        mysql_db="autoai",
    )
    base.update(overrides)
    return Namespace(**base)


def test_load_command_profile_from_file(tmp_path: Path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "focus_commands": ["chatgpt.sidebarView.focus", "workbench.action.chat.focusInput"],
                "input_command_candidates": ["chatgpt.ask"],
                "copy_commands": ["workbench.action.chat.copyItem"],
                "copy_wait_ms": 50,
            }
        ),
        encoding="utf-8",
    )
    worker = VscodeCodexWorker(_args(tmp_path, command_profile=str(profile_path)))
    p = worker.command_profile
    assert p["input_command_candidates"] == ["chatgpt.ask"]
    assert p["copy_commands"] == ["workbench.action.chat.copyItem"]
    assert p["copy_wait_ms"] == 50
