# tasktodo0203_C Hardening Plan (2026-03-03)

## Context / Baseline
- Goal: keep Codex path on VSCode Codex plugin + REST Control endpoint(s), with MySQL task flow unchanged.
- Required by wind:
  1. `one_click` should use configurable REST endpoint(s), not hardcoded single URL.
  2. If managing multiple Codex workers, support multiple REST endpoints.
  3. Keep command flow: input into Codex input box -> submit -> wait -> collect output -> write feedback.
  4. Do step-by-step delivery, each step with test evidence.

## Baseline Check Result (already measured)
- Local stack is alive (`dispatcher` + `vscode_codex_worker`).
- MySQL task `id=34` transitions: `pending -> dispatched -> failed`.
- Failure reason: `no clipboard delta in 120.0s`.
- Worker system feedback exists: `channel=system`, `step=collect_output`.
- REST command list available, but current copy strategy is unstable in this machine context.

## Phases

### Phase 1: Configurable REST Endpoint(s) in one_click
Scope:
- Add file-based REST endpoint config.
- Allow multiple Codex worker entries (`target`, `port`, `rest_url`).
- Auto-merge routing with configured Codex targets.

Deliverables:
- New config file under `config/`.
- `scripts/one_click.py` loader + startup loop for Codex workers.
- Tests for config parsing and arg wiring.

Gate:
- Unit tests pass for parsing and process arg generation.
- `one_click start --dry-run` shows configured target->port->rest_url mapping.

### Phase 2: Worker Command Pipeline Profile
Scope:
- Make worker command sequence configurable (focus/submit/copy strategy profile).
- Keep default profile backward-compatible.

Deliverables:
- Worker args/env config for command profile.
- Tests for command pipeline ordering by profile.

Gate:
- Unit tests pass for both default and configured profile.

### Phase 3: Output Collection Reliability
Scope:
- Add fallback collection path(s) when clipboard delta does not change.
- Keep strict no-rollback policy.

Deliverables:
- Improved collector with clear step-level diagnostics in `system_alert`.
- Tests for timeout/fallback branches.

Gate:
- `hello` smoke from MySQL task yields non-empty `db` feedback on this machine.

### Phase 4: End-to-End Verification
Scope:
- Private 3 checks with minimal noise.

Checks:
1. one_click loads REST config correctly.
2. single `codex` task from MySQL reaches worker and enters running/completed (or explicit failure with diagnostic).
3. feedback row for the task is produced (`db` or `system`) with actionable payload.

---

## Progress Log
- [x] Baseline measured and documented.
- [x] Phase 1 completed.
  - `one_click` now supports `--vscode-rest-config` (JSON workers list) and `--vscode-rest-map`.
  - Dry-run confirms single endpoint and multi-endpoint routing generation.
  - Tests: `tests/test_one_click_vscode_rest_config.py` pass.
- [x] Phase 2 completed.
  - `vscode_codex_worker` supports command profile (`focus/input/submit/copy/fallback` knobs).
  - Tests: `tests/test_vscode_codex_worker_profile.py` and pipeline sequence tests pass.
- [~] Phase 3 in progress.
  - Added fast-fail focus precheck:
    - worker checks `JSON.stringify(vscode.window.state)` before submit.
    - if `focused=false`, fail at step `window_focus` and emit system alert (no 120s empty wait).
  - New tests:
    - fail-fast on unfocused window
    - recovery when focus becomes true
  - Remaining: stable non-clipboard output extraction under current VSCode Codex session context.
- [ ] Phase 4 pending.

## Step Test Evidence
- One-click config tests:
  - `pytest -q tests/test_one_click_bridge_mode.py tests/test_one_click_codex_agent_routing.py tests/test_one_click_vscode_rest_config.py`
  - Result: `8 passed`
- Worker tests:
  - `pytest -q tests/test_vscode_codex_worker_pipeline.py tests/test_vscode_codex_worker_profile.py tests/test_vscode_codex_worker_mock_rest.py`
  - Result: `11 passed`
- One-click dry-run (single endpoint):
  - `python scripts/one_click.py start --dry-run --vscode-rest-config config/vscode_rest_targets.json`
  - Confirms `--rest-url http://127.0.0.1:49818` wiring to `vscode_codex_worker.py`.
- One-click dry-run (multi endpoint):
  - `python scripts/one_click.py start --dry-run --vscode-rest-map "codex=http://127.0.0.1:49818,codex_b=http://127.0.0.1:49819"`
  - Confirms generated routing: `codex=9003,codex_b=9004`.
