# FastAPI Orchestrator E2E Checklist

Current server runtime target:
- bind: `0.0.0.0:18080`
- firewall: allow `18080/tcp` (UFW/security-group)

## 1. Health

```bash
curl -s http://127.0.0.1:18080/healthz
```

Expected:

```json
{"status":"ok"}
```

If exposed for remote access, also verify from outside:

```bash
curl -s http://34.101.230.107:18080/healthz
```

## 1.1 Browser Console (remote)

Open:

```text
http://34.101.230.107:18080/console
```

Use fields:
- `target`
- `sessionid` (optional)
- `message`
- `api key` (if `ORCH_API_KEY` is enabled)

## 2. Telegram Inbound

Send in Telegram:

```text
/to codex summarize latest logs
```

Expected:
- bot replies `accepted task_id=...`
- one `pending` row appears in `ai_tasks`
- `ai_tasks.sessionid` should be filled (e.g. `tg:<chat_id>:codex`)

## 2.1 Local one-click start

```powershell
python .\scripts\one_click.py start
python .\scripts\one_click.py status
```

Expected:
- `bridge_codex` and `dispatcher` are `alive`

## 3. Local Worker Dispatch

Expected:
- local dispatcher picks that task and routes to codex bridge.

## 4. Feedback Roundtrip

Run locally (no DB password in CLI):

```powershell
python .\scripts\one_click.py feedback --task-id <id> --message "done" --source-ai codex
```

Expected:
- Telegram receives the feedback message
- `ai_feedback.delivered_tg` becomes `1`
- feedback header should include `sessionid=...` when available

## 5. Feedback Smoke Test Script (Cloud DB + Telegram)

Inject one synthetic feedback row, execute one outbound delivery cycle, and assert `delivered_tg=1`:

```powershell
python .\scripts\feedback_flow_test.py --inject --chat-id 1261596828 --payload "feedback smoke from script"
```

Expected:
- output contains `PASS feedback_id=... delivered_tg=1`
- Telegram receives one smoke message

## 6. Full Loop E2E (via ai_feedback.py)

This test verifies the exact production path:
- local `ai_feedback.py` inserts row to cloud `ai_feedback`
- cloud orchestrator outbound loop consumes it
- Telegram push succeeds
- DB `delivered_tg` flips to `1`

```powershell
python .\scripts\feedback_loop_e2e_test.py --chat-id 1261596828 --timeout-sec 40
```

Expected:
- output contains `PASS feedback_id=... delivered_tg=1`

Notes:
- If task is not created from Telegram (no `source_chat_id`), set `TELEGRAM_DEFAULT_CHAT_ID` in cloud `.env`.
