# Cloud Telegram Bot Worker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a cloud-side Telegram bot worker that writes inbound messages to `ai_tasks` and pushes `ai_feedback` back to Telegram, using cloud MySQL as the single cross-machine source of truth.

**Architecture:** Phase 1 uses Telegram long polling (no Flask required) to reduce server complexity and avoid reverse-proxy/webhook dependency. The service runs on `34.101.230.107` with `systemd`, connects to cloud MySQL, and cooperates with local AI workers (`dispatcher.py` + `window_bridge.py`). Optional Phase 2 adds a FastAPI control API only if external webhook/API integration is needed.

**Tech Stack:** Python 3.10+, `python-telegram-bot`, `PyMySQL`, `python-dotenv`, `pytest`, `systemd`.

---

## Scope Decision (Before Coding)

- **Chosen for now:** Telegram long polling worker (recommended).
- **Not needed now:** Flask service.
- **Optional later:** FastAPI admin/control API.

Reason:
- One-person operation, fastest stable path.
- No need to expose inbound HTTP endpoint.
- Matches your current requirement of shutting down existing reverse proxy/HTTP stack.

## Delivery Overview

1. Remote server operation tasks (cleanup, runtime, deploy).
2. Cloud bot code implementation tasks.
3. DB schema migration tasks.
4. Verification and go-live tasks.

---

### Task 1: Server Baseline And HTTP/Reverse Proxy Shutdown

**Files:**
- Create: `docs/runbooks/cloud-server-baseline.md`

**Step 1: Capture baseline status**

Run on `34.101.230.107`:

```bash
hostname
whoami
python3 --version
sudo systemctl list-unit-files --type=service | egrep 'nginx|apache2|caddy|traefik|haproxy' || true
sudo ss -lntup '( sport = :80 or sport = :443 )'
```

**Step 2: Stop and disable HTTP/reverse proxy services**

```bash
for s in nginx apache2 caddy traefik haproxy; do
  sudo systemctl stop "$s" 2>/dev/null || true
  sudo systemctl disable "$s" 2>/dev/null || true
done
sudo ss -lntup '( sport = :80 or sport = :443 )'
```

**Step 3: Record command output in runbook**
- Save before/after output in `docs/runbooks/cloud-server-baseline.md`.

---

### Task 2: Add Cloud Bot Dependencies And Config Module

**Files:**
- Modify: `requirements.txt`
- Create: `cloud_bot/config.py`
- Create: `cloud_bot/__init__.py`

**Step 1: Write failing config test**

Create `tests/test_cloud_bot_config.py`:

```python
import pytest
from cloud_bot.config import load_settings


def test_load_settings_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        load_settings()
```

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_cloud_bot_config.py -v
```

Expected: FAIL (`ModuleNotFoundError` or missing `load_settings`).

**Step 3: Write minimal implementation**
- Add dependencies:
  - `python-telegram-bot>=21.0`
  - `python-dotenv>=1.0`
  - `pytest>=8.0`
- Implement `load_settings()` in `cloud_bot/config.py`:
  - Read env vars.
  - Validate required values.
  - Return dataclass settings object.

**Step 4: Re-run test**

```bash
pytest tests/test_cloud_bot_config.py -v
```

Expected: PASS.

---

### Task 3: Implement MySQL Access Layer

**Files:**
- Create: `cloud_bot/db.py`
- Create: `tests/test_cloud_bot_db_queries.py`

**Step 1: Write failing tests for query builders**

```python
from cloud_bot.db import build_insert_task_sql, build_select_pending_feedback_sql


def test_insert_task_sql_contains_required_columns():
    sql = build_insert_task_sql()
    assert "ai_tasks" in sql
    assert "ai_target" in sql
    assert "message" in sql


def test_select_pending_feedback_sql_filters_undelivered():
    sql = build_select_pending_feedback_sql()
    assert "ai_feedback" in sql
    assert "delivered_tg=0" in sql.replace(" ", "")
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_cloud_bot_db_queries.py -v
```

Expected: FAIL.

**Step 3: Write minimal implementation**
- Implement DB helpers in `cloud_bot/db.py`:
  - connect
  - insert task from Telegram
  - fetch undelivered feedback
  - mark feedback delivered

**Step 4: Re-run test**

```bash
pytest tests/test_cloud_bot_db_queries.py -v
```

Expected: PASS.

---

### Task 4: Telegram Inbound -> ai_tasks

**Files:**
- Create: `cloud_bot/inbound.py`
- Create: `tests/test_cloud_bot_inbound.py`

**Step 1: Write failing parse tests**

```python
from cloud_bot.inbound import parse_task_message


def test_parse_to_command():
    target, message = parse_task_message("/to claude analyze logs")
    assert target == "claude"
    assert message == "analyze logs"
```

**Step 2: Run test**

```bash
pytest tests/test_cloud_bot_inbound.py -v
```

Expected: FAIL.

**Step 3: Implement parser + insert integration**
- Command contract:
  - `/to <ai_target> <message>`
  - `ai_target:message` (fallback plain format)
- On valid input, insert row into `ai_tasks` as `pending`.
- Persist source metadata:
  - `source_channel='telegram'`
  - `source_chat_id`
  - `source_user_id`

**Step 4: Re-run tests**

```bash
pytest tests/test_cloud_bot_inbound.py -v
```

Expected: PASS.

---

### Task 5: ai_feedback -> Telegram Outbound

**Files:**
- Create: `cloud_bot/outbound.py`
- Create: `tests/test_cloud_bot_outbound.py`

**Step 1: Write failing formatter test**

```python
from cloud_bot.outbound import format_feedback_message


def test_format_feedback_message():
    row = {"task_id": "12", "source_ai": "codex", "payload": "done"}
    text = format_feedback_message(row)
    assert "task_id=12" in text
    assert "codex" in text
    assert "done" in text
```

**Step 2: Run test**

```bash
pytest tests/test_cloud_bot_outbound.py -v
```

Expected: FAIL.

**Step 3: Implement outbound worker**
- Poll undelivered feedback rows.
- Resolve destination chat:
  - Prefer mapping via `task_id -> ai_tasks.source_chat_id`.
- Send message to Telegram.
- Mark feedback delivered (`delivered_tg=1`, `delivered_tg_at=NOW()`).

**Step 4: Re-run tests**

```bash
pytest tests/test_cloud_bot_outbound.py -v
```

Expected: PASS.

---

### Task 6: Bot Application Entrypoint

**Files:**
- Create: `cloud_bot/main.py`
- Create: `tests/test_cloud_bot_main_wiring.py`

**Step 1: Write failing wiring test**

```python
from cloud_bot.main import build_application


def test_build_application_returns_app():
    app = build_application("token")
    assert app is not None
```

**Step 2: Run test**

```bash
pytest tests/test_cloud_bot_main_wiring.py -v
```

Expected: FAIL.

**Step 3: Implement bot startup**
- Register handlers:
  - `/start`
  - `/help`
  - `/to`
  - plain text fallback
- Start polling loop.
- Start outbound delivery loop (background job).

**Step 4: Re-run test**

```bash
pytest tests/test_cloud_bot_main_wiring.py -v
```

Expected: PASS.

---

### Task 7: DB Migration For Telegram Delivery State

**Files:**
- Create: `migrations/2026-03-02-cloud-bot.sql`
- Modify: `dispatcher.py` (status compatibility only if needed)
- Modify: `ai_feedback.py` (optional `channel` normalization)

**Step 1: Write migration SQL**

Required changes:
- `ai_tasks` add:
  - `source_channel VARCHAR(32) NULL`
  - `source_chat_id VARCHAR(64) NULL`
  - `source_user_id VARCHAR(64) NULL`
  - `idempotency_key VARCHAR(128) NULL`
- `ai_feedback` add:
  - `delivered_tg TINYINT NOT NULL DEFAULT 0`
  - `delivered_tg_at DATETIME NULL`
- Add indexes:
  - `idx_tasks_status_priority`
  - `idx_feedback_delivered`
  - unique index on `idempotency_key` (nullable)

**Step 2: Run migration on cloud MySQL**

```bash
mysql -h <cloud_host> -u <user> -p <db_name> < migrations/2026-03-02-cloud-bot.sql
```

Expected: `Query OK` for all statements.

---

### Task 8: Deployment Packaging And systemd Service

**Files:**
- Create: `deploy/systemd/autoai-cloud-bot.service`
- Create: `deploy/env/.env.cloud-bot.example`
- Create: `scripts/deploy_cloud_bot.sh`

**Step 1: Add systemd unit**
- `ExecStart` points to venv python and `cloud_bot.main`.
- `WorkingDirectory` points repo path on server.
- `Restart=always`.

**Step 2: Add env template**

Variables:
- `TELEGRAM_BOT_TOKEN`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DB`
- `BOT_POLL_INTERVAL_SEC`
- `OUTBOUND_POLL_INTERVAL_SEC`

**Step 3: Deploy and start**

```bash
sudo cp deploy/systemd/autoai-cloud-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autoai-cloud-bot
sudo systemctl start autoai-cloud-bot
sudo systemctl status autoai-cloud-bot --no-pager
```

Expected: service status `active (running)`.

---

### Task 9: Telegram BotFather Command Standardization

**Files:**
- Create: `docs/runbooks/telegram-botfather-commands.md`

**Step 1: Set BotFather commands**

```
start - Start bot and show usage
help - Show command help
to - Send task to specific AI: /to <claude|gemini|codex> <message>
status - Query task status by task id
myid - Show current chat id
```

**Step 2: Verify in Telegram UI**
- Open bot profile and confirm command list visible.

---

### Task 10: End-to-End Verification

**Files:**
- Create: `docs/runbooks/e2e-checklist.md`

**Step 1: In Telegram send inbound task**

```text
/to codex summarize latest logs
```

Expected:
- One row inserted into `ai_tasks` with `status='pending'`.

**Step 2: Verify local dispatcher picks task**
- Confirm local logs show dispatch to target port.

Expected:
- `ai_tasks.status` transitions to `dispatching` then `dispatched/running` depending on implementation.

**Step 3: Send feedback from local AI**

```bash
python ai_feedback.py --source-ai codex --task-id <id> --db "done"
```

Expected:
- New row in `ai_feedback` and then Telegram receives push.
- `delivered_tg=1`.

**Step 4: Commit**

```bash
git add .
git commit -m "feat: add cloud telegram bot worker with mysql task/feedback bridge"
```

---

## Server Execution Checklist (for `34.101.230.107`)

1. Ensure SSH login with `lianping1230`.
2. Stop/disable existing HTTP/reverse proxy services.
3. Prepare Python runtime and venv.
4. Deploy project files and `.env`.
5. Run DB migration.
6. Start and enable `autoai-cloud-bot` service.
7. Execute E2E checklist.

## Open Questions Before Execution

1. Confirm Telegram bot token is ready and can be used on this server.
2. Confirm cloud MySQL host/user/password/db and source IP whitelist for this server.
3. Confirm command grammar to keep: `/to <ai> <message>` (recommended).

Plan complete and saved to `docs/plans/2026-03-02-cloud-telegram-bot-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) - execute task-by-task with review checkpoints.
2. Parallel Session (separate) - execute via dedicated session focused on plan batches.

Which approach?
