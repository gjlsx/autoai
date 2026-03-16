import json
from pathlib import Path

from scripts import chonky_remote_pilot_probe as probe


def test_evaluate_repo_detects_tool_contract(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src" / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "extension.ts").write_text(
        "const t = vscode.lm.registerTool('chonky_remotepilot', remoteChatTool);",
        encoding="utf-8",
    )
    (repo / "src" / "tools" / "remoteChat.ts").write_text(
        "transportManager.waitForMessage(token);\ntransportManager.sendMessage('c','t','x');\n"
        "MUST call chonky_remotepilot again",
        encoding="utf-8",
    )

    out = probe.evaluate_repo(repo)
    assert out["repo_exists"] is True
    assert out["supports_input_output_via_tool"] is True


def test_evaluate_runtime_collects_command_flags(monkeypatch):
    sample = [
        "chatgpt.sidebarView.focus",
        "workbench.action.chat.focusInput",
        "workbench.action.chat.submit",
        "chonky.remotepilot.configureTelegram",
    ]
    monkeypatch.setattr(probe, "_http_post_json", lambda *args, **kwargs: sample)
    out = probe.evaluate_runtime("http://127.0.0.1:49818", timeout=3)
    assert out["rest_reachable"] is True
    assert out["commands_total"] == 4
    assert out["chonky_commands"] == ["chonky.remotepilot.configureTelegram"]


def test_decide_prefers_fallback_when_runtime_not_ready():
    repo_eval = {"supports_input_output_via_tool": True}
    runtime_eval = {"rest_reachable": True, "chonky_commands": []}
    d = probe.decide(repo_eval, runtime_eval)
    assert d["usable_for_current_pipeline"] is False
    assert "fallback_to_task2_recommended" in d["reasons"]

