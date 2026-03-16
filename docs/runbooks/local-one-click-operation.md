# Local One-Click Operation

## Goal
- No manual terminal input loop.
- No MySQL password in command-line arguments.
- `codex` path fixed to VSCode Codex plugin + REST Control (no PTY fallback).
- One command to start local stack, one to stop, one to check status.

## Prerequisite
- `.env` exists at repo root (`autoai/.env`).
- VSCode has `openai.chatgpt` and `dpar39.vscode-rest-control` installed.
- REST Control is listening on `http://127.0.0.1:49818` (default).
- Cloud FastAPI orchestrator is already running on server.

## Start (one command)

```powershell
python .\scripts\one_click.py start
```

What it does:
- parses MySQL config from `.env` (legacy note format supported)
- starts local `vscode_codex_worker.py` for `codex` on `127.0.0.1:9003` (default)
- starts `dispatcher.py` with `--no-user-input`
- routes `ai_target=codex` to VSCode worker port `9003`
- injects `MYSQL_*` via process environment (not CLI args)
- auto-recovers stale mysql tasks stuck in `dispatching`
- writes runtime state to `.runtime/local_stack_state.json`

If you route tasks to Claude/Gemini, start with switches:

```powershell
python .\scripts\one_click.py start --start-claude
python .\scripts\one_click.py start --start-claude --start-gemini
```

If you need old bridge mode for Claude/Gemini:

```powershell
python .\scripts\one_click.py start --bridge-mode window
```

If you still need optional codex agent targets (`codex_sdk` / `codex_app`):

```powershell
python .\scripts\one_click.py start --start-codex-agent
```

## Status

```powershell
python .\scripts\one_click.py status
```

Shows:
- process alive/dead state
- active run log file paths
- mysql target summary

## Stop

```powershell
python .\scripts\one_click.py stop
```

What it does:
- stops processes from state file
- fallback cleanup by script commandline (`vscode_codex_worker.py`, `pty_worker.py`, `codex_agent_worker.py`, `window_bridge.py`, `dispatcher.py`)
- fallback cleanup by local ports (`9001/9002/9003/9013`)

## One-click feedback (no password on CLI)

```powershell
python .\scripts\one_click.py feedback --task-id 2 --message "done" --source-ai codex
```

What it does:
- parses MySQL from `.env`
- sets `MYSQL_*` env for current process only
- calls `ai_feedback.py` without passing DB password via command args

## Verification Checklist

1. In Telegram:
   - send `/to codex hello`
   - expect `accepted task_id=<id>, target=codex`
2. Local:
   - run `python scripts/one_click.py start`
   - run `python scripts/one_click.py status` and confirm codex worker + dispatcher are alive
3. Feedback:
   - run `python scripts/one_click.py feedback ...` with that task id
   - expect Telegram gets feedback push

4. PTY full-pipeline smoke:
   - run `python scripts/e2e_pty_pipeline_smoke.py --timeout-sec 120 --port 9913`
   - expect `PASS: task=... dispatched, feedback_id=...`

5. Codex-agent full-pipeline smoke:
   - run `python scripts/e2e_codex_agent_pipeline_smoke.py --timeout-sec 120 --port 9923`
   - expect `[e2e-codex-agent] PASS: ...`

## Troubleshooting

1. Bridge dead immediately:
- check `bridge_codex_err_log` from status output
- verify REST Control is reachable: `curl http://127.0.0.1:49818 -d "{\"command\":\"custom.getCommands\"}"`
- verify command exists: `chatgpt.sidebarView.focus`

2. Task stuck in `dispatching`:
- restart one-click stack; dispatcher auto-recovers stale dispatching tasks (default 60s)

3. Port conflict on `9003`:
- run `python scripts/one_click.py stop` first, then start again

4. `codex` retries then fails:
- `vscode_codex_worker.py` has fixed retry=3 per step, no fallback to PTY/CLI
- on 3 failures it writes `ai_feedback.channel=system` and marks `ai_tasks.status=failed`
- when stream exists but text cannot be extracted, feedback text will be:
  - `codex stream observed; full text is in VSCode Codex sidebar.`

5. `codex_sdk` / `codex_app` task does not dispatch:
- run `python scripts/one_click.py status`
- confirm `codex_agent_pid` is alive and `routing` contains `codex_sdk=9013,codex_app=9013` (or your custom port)
