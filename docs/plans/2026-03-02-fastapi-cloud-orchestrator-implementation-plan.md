# FastAPI Cloud Orchestrator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a cloud-side FastAPI orchestrator on `34.101.230.107` that bridges Telegram and cloud MySQL (`ai_tasks` / `ai_feedback`) for your local AI workers.

**Architecture:** Use FastAPI as the manager service/API node, with Telegram in polling mode first (no public webhook dependency). FastAPI exposes internal APIs (`/healthz`, task APIs), while background workers handle Telegram inbound (write `ai_tasks`) and outbound (read `ai_feedback`, send to Telegram, mark delivered).

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, python-telegram-bot, PyMySQL, python-dotenv, pytest, systemd.

---

## Implementation Notes

- Use **FastAPI** (confirmed by you).
- Telegram first phase uses **polling**, not webhook, to avoid HTTPS/reverse-proxy requirement.
- Keep current local side unchanged first: `dispatcher.py + window_bridge.py + ai_feedback.py`.

---

### Task 1: Server Preparation And Existing HTTP/Proxy Shutdown

**Files:**
- Create: `docs/runbooks/2026-03-02-server-prep.md`

**Step 1: Baseline capture on server**

```bash
hostname
whoami
python3 --version
sudo ss -lntup '( sport = :80 or sport = :443 )'
sudo systemctl list-unit-files --type=service | egrep 'nginx|apache2|caddy|traefik|haproxy' || true
```

**Step 2: Stop and disable legacy services**

```bash
for s in nginx apache2 caddy traefik haproxy; do
  sudo systemctl stop "$s" 2>/dev/null || true
  sudo systemctl disable "$s" 2>/dev/null || true
done
sudo ss -lntup '( sport = :80 or sport = :443 )'
```

**Step 3: Save output in runbook**
- Record before/after for audit.

---

### Task 2: Add Dependencies And App Skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `cloud_orchestrator/__init__.py`
- Create: `cloud_orchestrator/main.py`
- Create: `cloud_orchestrator/config.py`
- Create: `tests/test_orchestrator_config.py`

**Step 1: Write failing config test**

```python
import pytest
from cloud_orchestrator.config import load_settings


def test_missing_bot_token_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        load_settings()
```

**Step 2: Run test and confirm fail**

```bash
pytest tests/test_orchestrator_config.py -v
```

**Step 3: Implement minimal config loader**
- Dataclass settings from env.
- Required fields:
  - `TELEGRAM_BOT_TOKEN`
  - `MYSQL_HOST`
  - `MYSQL_PORT`
  - `MYSQL_USER`
  - `MYSQL_PASSWORD`
  - `MYSQL_DB`

**Step 4: Re-run test**

```bash
pytest tests/test_orchestrator_config.py -v
```

---

### Task 3: Database Migration For Telegram Roundtrip

**Files:**
- Create: `migrations/2026-03-02-fastapi-orchestrator.sql`
- Create: `tests/test_migration_sql_smoke.py`

**Step 1: Write SQL smoke test (string-level)**

```python
from pathlib import Path


def test_migration_contains_delivery_columns():
    sql = Path("migrations/2026-03-02-fastapi-orchestrator.sql").read_text(encoding="utf-8")
    assert "delivered_tg" in sql
    assert "idempotency_key" in sql
```

**Step 2: Run test (expected fail)**

```bash
pytest tests/test_migration_sql_smoke.py -v
```

**Step 3: Add migration SQL**
- `ai_tasks` add:
  - `source_channel`
  - `source_chat_id`
  - `source_user_id`
  - `idempotency_key`
- `ai_feedback` add:
  - `delivered_tg TINYINT DEFAULT 0`
  - `delivered_tg_at DATETIME NULL`
- indexes:
  - `idx_tasks_status_priority`
  - `idx_feedback_delivered`
  - unique `idempotency_key` (nullable)

**Step 4: Re-run test**

```bash
pytest tests/test_migration_sql_smoke.py -v
```

---

### Task 4: MySQL Data Access Layer

**Files:**
- Create: `cloud_orchestrator/db.py`
- Create: `tests/test_orchestrator_db_sql.py`

**Step 1: Write failing query tests**

```python
from cloud_orchestrator.db import SQL


def test_insert_task_sql_targets_ai_tasks():
    assert "INSERT INTO ai_tasks" in SQL.INSERT_TASK


def test_select_feedback_sql_filters_undelivered():
    assert "delivered_tg = 0" in SQL.SELECT_UNDELIVERED_FEEDBACK
```

**Step 2: Run tests (fail)**

```bash
pytest tests/test_orchestrator_db_sql.py -v
```

**Step 3: Implement db helpers**
- connect()
- insert_task_from_telegram()
- fetch_undelivered_feedback()
- mark_feedback_delivered()
- get_task_status()

**Step 4: Re-run tests**

```bash
pytest tests/test_orchestrator_db_sql.py -v
```

---

### Task 5: Telegram Inbound Worker (Polling) -> ai_tasks

**Files:**
- Create: `cloud_orchestrator/telegram_inbound.py`
- Create: `tests/test_telegram_inbound_parser.py`

**Step 1: Write failing parser tests**

```python
from cloud_orchestrator.telegram_inbound import parse_command


def test_parse_to_command():
    target, message = parse_command("/to codex summarize logs")
    assert target == "codex"
    assert message == "summarize logs"
```

**Step 2: Run tests (fail)**

```bash
pytest tests/test_telegram_inbound_parser.py -v
```

**Step 3: Implement inbound logic**
- Support:
  - `/to <claude|gemini|codex> <message>`
  - `ai_target:message` fallback
- Write task row with `status='pending'`, `source_channel='telegram'`.

**Step 4: Re-run tests**

```bash
pytest tests/test_telegram_inbound_parser.py -v
```

---

### Task 6: Telegram Outbound Worker ai_feedback -> Telegram

**Files:**
- Create: `cloud_orchestrator/telegram_outbound.py`
- Create: `tests/test_telegram_outbound_format.py`

**Step 1: Write failing formatter test**

```python
from cloud_orchestrator.telegram_outbound import format_feedback


def test_format_feedback_contains_task_and_ai():
    text = format_feedback({"task_id": "11", "source_ai": "claude", "payload": "done"})
    assert "task_id=11" in text
    assert "claude" in text
```

**Step 2: Run tests (fail)**

```bash
pytest tests/test_telegram_outbound_format.py -v
```

**Step 3: Implement outbound polling loop**
- Poll undelivered `ai_feedback`.
- Resolve destination chat by `task_id -> ai_tasks.source_chat_id`.
- Send to Telegram.
- Mark delivered.

**Step 4: Re-run tests**

```bash
pytest tests/test_telegram_outbound_format.py -v
```

---

### Task 7: FastAPI Endpoints And Lifespan Wiring

**Files:**
- Modify: `cloud_orchestrator/main.py`
- Create: `cloud_orchestrator/api.py`
- Create: `tests/test_api_routes.py`

**Step 1: Write failing route tests**

```python
from fastapi.testclient import TestClient
from cloud_orchestrator.main import app


def test_healthz():
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
```

**Step 2: Run tests (fail)**

```bash
pytest tests/test_api_routes.py -v
```

**Step 3: Implement minimal APIs**
- `GET /healthz`
- `POST /api/tasks` (manual task inject)
- `GET /api/tasks/{task_id}` (status query)
- Start inbound/outbound workers in app lifespan.

**Step 4: Re-run tests**

```bash
pytest tests/test_api_routes.py -v
```

---

### Task 8: BotFather Command Spec And Docs

**Files:**
- Create: `docs/runbooks/telegram-bot-commands.md`

**Step 1: Define command set**

```text
start - show bot usage
help - show commands
to - create task: /to <claude|gemini|codex> <message>
status - query task status by id
myid - show current chat id
```

**Step 2: Add runbook screenshots/checkpoints**
- Capture bot command setup completion checklist.

---

### Task 9: Deployment Scripts And systemd Service

**Files:**
- Create: `deploy/systemd/autoai-fastapi-orchestrator.service`
- Create: `deploy/env/.env.fastapi-orchestrator.example`
- Create: `scripts/deploy_fastapi_orchestrator.sh`

**Step 1: Create service unit**
- `ExecStart=/path/to/venv/bin/uvicorn cloud_orchestrator.main:app --host 127.0.0.1 --port 18080`
- `Restart=always`
- `EnvironmentFile=/path/to/.env`

**Step 2: Create env template**
- include Telegram and MySQL vars.

**Step 3: Deploy**

```bash
sudo cp deploy/systemd/autoai-fastapi-orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autoai-fastapi-orchestrator
sudo systemctl start autoai-fastapi-orchestrator
sudo systemctl status autoai-fastapi-orchestrator --no-pager
```

---

### Task 10: End-to-End Verification

**Files:**
- Create: `docs/runbooks/fastapi-orchestrator-e2e.md`

**Step 1: Health check**

```bash
curl -s http://127.0.0.1:18080/healthz
```

Expected: `{"status":"ok"}`.

**Step 2: Telegram inbound test**
- Send: `/to codex summarize logs`

Expected:
- new `ai_tasks` row with `pending`.

**Step 3: Local worker dispatch test**
- Local dispatcher picks task and routes to codex bridge.

Expected:
- status moves `pending -> dispatching -> dispatched/running`.

**Step 4: Feedback roundtrip**

```bash
python ai_feedback.py --source-ai codex --task-id <id> --db "done"
```

Expected:
- Telegram receives result.
- `ai_feedback.delivered_tg=1`.

**Step 5: Full test run**

```bash
pytest -v
```

Expected: all pass.

---

## Server Tasks Summary (34.101.230.107)

1. Stop/disable old reverse proxy + HTTP services.
2. Deploy FastAPI orchestrator code and `.env`.
3. Run MySQL migration.
4. Start `systemd` service.
5. Validate E2E with Telegram and local AI workers.

## Required Inputs Before Execution

1. `TELEGRAM_BOT_TOKEN`
2. Cloud MySQL: host, port, user, password, db
3. Confirm allowed AI targets: `claude, gemini, codex`
4. Confirm service listen policy:
   - recommended now: `127.0.0.1:18080` (internal only)
   - optional later: public with TLS + reverse proxy

Plan complete and saved to `docs/plans/2026-03-02-fastapi-cloud-orchestrator-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) - execute task-by-task with checkpoints.
2. Parallel Session (separate) - execute in a dedicated session with plan batches.

Which approach?
