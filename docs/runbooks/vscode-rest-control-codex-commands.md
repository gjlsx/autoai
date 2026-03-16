# VSCode Codex + REST Control Commands

## Endpoint
- Default: `http://127.0.0.1:49818`
- Request format:

```json
{
  "command": "<command-id>",
  "args": []
}
```

## Core Command IDs (verified)
- `chatgpt.openSidebar`
- `chatgpt.sidebarView.focus`
- `workbench.action.chat.focusInput`
- `chatgpt.addToThread` (Primary injection)
- `workbench.action.chat.copyAll`
- `chatgpt.newChat`
- `custom.getCommands`
- `custom.eval`

## Fixed Pipeline Used By `vscode_codex_worker.py` (Implemented)
> **[NEW]** The pipeline is now **command-driven**. It dynamically resolves commands using `custom.getCommands` and prefers direct input injection like `chatgpt.addToThread`.
1. **Focus:** `chatgpt.sidebarView.focus` (or similar focus commands from profile).
2. **Session Isolation:** `chatgpt.newChat` (if `sessionid` changed and `--new-chat-on-session-change` is enabled).
3. **Baseline Snapshot:** `workbench.action.chat.copyAll` + `custom.eval("vscode.env.clipboard.readText()")`.
4. **Command Resolution:** `custom.getCommands` to find a valid injection command from `input_command_candidates` (default: `chatgpt.addToThread`, `codex.addToThread`, `chatgpt.ask`).
5. **Injection:** Invoke the resolved command with the message as an argument.
6. **Polling loop:**
   - `workbench.action.chat.copyAll`
   - `custom.eval("vscode.env.clipboard.readText()")`
   - Delta extraction and feedback emission.
   - Stream monitoring via `output:openai.chatgpt.Codex.log` (look for `thread-stream-state-changed`).

Current behavior:
- If clipboard delta is available: emit actual delta text.
- If clipboard delta is unavailable but Codex stream events are seen in `output:openai.chatgpt.Codex.log`: emit
  `codex stream observed; full text is in VSCode Codex sidebar.`
- If Codex log contains hard failures (for example `Failed to apply patches for conversationId=...`): worker marks
  task failed and emits `channel=system` alert payload.
- If neither signal is available before timeout: trigger retry/alert flow.

## Quick Checks

### 1) List commands
```powershell
@'
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:49818",
    data=json.dumps({"command":"custom.getCommands"}).encode("utf-8"),
    headers={"Content-Type":"application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=5).read().decode("utf-8")[:500])
'@ | python -
```

### 2) Focus Codex sidebar
```powershell
@'
import json, urllib.request
payload = {"command":"chatgpt.sidebarView.focus"}
req = urllib.request.Request(
    "http://127.0.0.1:49818",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type":"application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
'@ | python -
```

### 3) Read clipboard via `custom.eval`
```powershell
@'
import json, urllib.request
payload = {"command":"custom.eval","args":["vscode.env.clipboard.readText()"]}
req = urllib.request.Request(
    "http://127.0.0.1:49818",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type":"application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
'@ | python -
```

## Failure Policy (implemented)
- No fallback to PTY/CLI for `codex`.
- Each critical step retries `3` times.
- After `3` failures:
  - write `ai_feedback` `channel=system` with `task_id/sessionid/step/retries/last_error`
  - update `ai_tasks.status='failed'` and `last_error`
  - cloud outbound loop sends Telegram alert to `source_chat_id` first.
