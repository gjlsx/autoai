from argparse import Namespace

from scripts.one_click import build_bridge_or_worker_args


def make_args(**kwargs):
    base = dict(
        bridge_mode="pty",
        pty_feedback_mode="ai_feedback",
        pty_feedback_channel="db",
        pty_feedback_file="",
        pty_backend="auto",
        pty_emit_input_events=False,
        vscode_rest_url="http://127.0.0.1:49818",
        vscode_command_profile="config/vscode_codex_command_profile.json",
        vscode_max_retries=3,
        vscode_response_timeout_sec=120.0,
        vscode_poll_interval_sec=1.0,
    )
    base.update(kwargs)
    return Namespace(**base)


def test_build_worker_args_for_pty_mode():
    args = make_args(bridge_mode="pty")
    proc = build_bridge_or_worker_args(args, ai="codex", port=9003, cli="codex", python_exe="python")
    assert proc[0:2] == ["-u", "vscode_codex_worker.py"]
    assert "--feedback-mode" in proc
    assert "--feedback-channel" in proc


def test_build_worker_args_for_window_mode():
    args = make_args(bridge_mode="window")
    proc = build_bridge_or_worker_args(args, ai="codex", port=9003, cli="codex", python_exe="python")
    assert proc[0:2] == ["-u", "vscode_codex_worker.py"]
