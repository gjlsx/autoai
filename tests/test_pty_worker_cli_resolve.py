import os

from pty_worker import PtyWorker


def test_resolve_cli_spawn_wraps_cmd(monkeypatch):
    def fake_which(name: str):
        if name == "codex.cmd":
            return r"C:\tools\codex.cmd"
        return None

    monkeypatch.setattr("pty_worker.shutil.which", fake_which)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

    app, cmdline = PtyWorker.resolve_cli_spawn("codex --help")
    assert app.lower().endswith("cmd.exe")
    assert cmdline is not None
    assert "/c" in cmdline
    assert "codex.cmd" in cmdline
    assert "--help" in cmdline


def test_resolve_cli_spawn_uses_exe_direct(monkeypatch):
    def fake_which(name: str):
        if name == "python.exe":
            return r"C:\Python\python.exe"
        return None

    monkeypatch.setattr("pty_worker.shutil.which", fake_which)
    app, cmdline = PtyWorker.resolve_cli_spawn("python.exe scripts\\mock_ai_cli.py")
    assert app == r"C:\Python\python.exe"
    assert cmdline is not None
    assert "mock_ai_cli.py" in cmdline
    assert "/c" not in cmdline.lower()
