# PTY Worker Integration Log

Date: 2026-03-02

> Note: as of `tasktodo0203_C`, `codex` production path is now `vscode_codex_worker.py` (VSCode REST Control). PTY path is retained as backup for non-codex targets/testing.

## Scope
- Integrate PTY Worker into local AutoAI dispatch pipeline:
  - `dispatcher.py` dispatches socket task payload
  - `pty_worker.py` receives task, writes to AI CLI PTY, reads output
  - `ai_feedback.py` writes standardized feedback event rows into MySQL `ai_feedback`

## Final Path
1. `ai_tasks.status='pending'` row exists in cloud MySQL.
2. `dispatcher.py` polls and marks row `dispatching`.
3. `dispatcher.py` routes by `ai_target` to local PTY worker socket port.
4. `pty_worker.py` writes message to CLI and reads streamed output.
5. `pty_worker.py` emits standardized events through `ai_feedback.py` (`channel=db`).
6. MySQL `ai_feedback` receives rows with `task_id=<task id>`.

## Key Changes
- `scripts/one_click.py` default bridge mode changed to `pty`.
- Added `--bridge-mode pty|window` for compatibility.
- Added `scripts/e2e_pty_pipeline_smoke.py` for full chain smoke test.
- Added PTY/backend/unit tests for parser, mode selection, and socket->PTY->event path.

## Real Smoke Test (Executed)
Command:

```powershell
python .\scripts\e2e_pty_pipeline_smoke.py --timeout-sec 120 --port 9913
```

Observed result:
- inserted `ai_tasks` row: `task_id=18`
- final status: `dispatched`
- feedback row seen with `task_id=18`, including `MOCK_AI_ECHO:...`
- command output: `PASS`

Re-run after one-click integration:
- `task_id=20`
- command output: `PASS`

## Main Issues and Fixes

1. `WinptyError: 系统找不到指定的文件`
- Cause:
  - `pywinpty` cannot reliably spawn `codex` shim by plain command name.
- Fix:
  - Implemented executable resolution in `pty_worker.py`:
    - search `.cmd/.bat/.exe` in PATH
    - for `.cmd/.bat`, spawn via `cmd.exe /c ...`

2. Unicode output crash in Windows console (`UnicodeEncodeError` with GBK)
- Cause:
  - PTY output contains non-GBK glyphs when feedback mode is `stdout`.
- Fix:
  - Added safe stdout/stderr writers using UTF-8 fallback with `errors="replace"`.

3. `node-pty` probe install failed on Windows
- Cause:
  - using `npm` literal executable can fail in some Windows shells.
- Fix:
  - probe runner now uses `npm.cmd` on Windows.

4. E2E false negative due dispatcher interference
- Cause:
  - existing local dispatcher instances could consume test task first.
- Fix:
  - E2E script now calls `one_click.py stop` before start.
  - uses dedicated `ai_target=codex_e2e` and dedicated routing port.

## How To Run Integration Now
- Default (PTY mode):

```powershell
python .\scripts\one_click.py start
```

- Legacy compatibility mode:

```powershell
python .\scripts\one_click.py start --bridge-mode window
```

- Verify:

```powershell
python .\scripts\one_click.py status
```

## One-Click End-to-End Validation (Executed)
Executed with mock CLI wired through one-click:

```powershell
python .\scripts\one_click.py start --codex-cli "python scripts/mock_ai_cli.py"
```

Inserted test task in MySQL (`ai_target=codex`), observed:
- task `id=19` -> `status=dispatched`
- feedback rows include:
  - output echo line
  - `MOCK_AI_ECHO:oneclick-pty-smoke-...`

## Task0203_b Extension (Codex Agent Worker)
- Added alternative worker: `codex_agent_worker.py`
- Purpose:
  - Keep a long-lived agent session model (sdk/app-server style) as an alternative to PTY CLI.
  - Select backend by `ai_target` (`codex_sdk` / `codex_app`).

### Main Issues and Fixes (Task0203_b)
1. Need test-first integration while keeping existing PTY path stable.
- Fix:
  - Added dedicated tests first:
    - parse + backend route unit tests
    - file feedback integration test
    - one_click routing injection tests
  - PTY tests remained unchanged and still pass.

2. one_click routing and process management only handled `codex/claude/gemini`.
- Fix:
  - Added `compose_routing_with_codex_agent(...)`.
  - Added `codex_agent_pid` state, log entries, stop/status handling.
  - Added cleanup for `codex_agent_worker.py` and default port `9013`.

3. Real SDK/App-server environments may not be ready on all developer machines.
- Fix:
  - Default `codex_agent_worker` provider is `mock` to ensure one-click startup is deterministic.
  - Added explicit provider switches:
    - `--codex-sdk-provider`
    - `--codex-app-provider`
    - `--codex-agent-app-server-url`
    - command template options for subprocess mode.

### E2E Smoke (Task0203_b)
```powershell
python .\scripts\e2e_codex_agent_pipeline_smoke.py --timeout-sec 120 --port 9923
```

Observed result:
- inserted `ai_tasks`: one `codex_sdk`, one `codex_app`
- both rows moved to `dispatched`
- `ai_feedback` contains `MOCK_SDK_REPLY:*` and `MOCK_APP_REPLY:*`
- output: `PASS`
