from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from cloud_orchestrator import db
from cloud_orchestrator.config import Settings

MIN_AUTH_KEY = "autoai_min_auth_2026"


class TaskCreateRequest(BaseModel):
    ai_target: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    priority: int = 0
    source_channel: Optional[str] = None
    source_chat_id: Optional[str] = None
    source_user_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    sessionid: Optional[str] = Field(default=None, max_length=77)


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    expected_api_key = settings.api_key or MIN_AUTH_KEY

    def require_api_key(x_api_key: str = Header(default="")) -> None:
        if x_api_key != expected_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")

    def require_console_key(k: str = Query(default=""), x_api_key: str = Header(default="")) -> None:
        if k == expected_api_key or x_api_key == expected_api_key:
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid console key")

    @router.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @router.post("/api/tasks", dependencies=[Depends(require_api_key)])
    def create_task(payload: TaskCreateRequest):
        if payload.ai_target.lower() not in settings.allowed_ai_targets:
            raise HTTPException(status_code=400, detail="unsupported ai_target")
        task_id = db.insert_task(
            settings,
            db.TaskInsert(
                ai_target=payload.ai_target.lower(),
                message=payload.message,
                priority=payload.priority,
                source_channel=payload.source_channel,
                source_chat_id=payload.source_chat_id,
                source_user_id=payload.source_user_id,
                idempotency_key=payload.idempotency_key,
                sessionid=payload.sessionid,
            ),
        )
        return {"task_id": task_id, "status": "pending"}

    @router.get("/api/tasks/{task_id}", dependencies=[Depends(require_api_key)])
    def get_task(task_id: int):
        row = db.get_task_status(settings, task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="task not found")
        return row

    @router.get("/api/feedback", dependencies=[Depends(require_api_key)])
    def get_feedback(task_id: int = Query(..., ge=1), limit: int = Query(100, ge=1, le=500)):
        return {"task_id": task_id, "items": db.fetch_feedback_by_task_id(settings, task_id=task_id, limit=limit)}

    @router.get("/console", response_class=HTMLResponse, dependencies=[Depends(require_console_key)])
    def console_page():
        options = "\n".join(
            f'<option value="{name}">{name}</option>'
            for name in settings.allowed_ai_targets
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AutoAI Console</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background: #f4f6fb; }}
    .card {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.08); padding: 16px; max-width: 980px; }}
    .row {{ display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }}
    label {{ display: block; font-size: 13px; color: #333; margin-bottom: 4px; }}
    input, select, textarea, button {{ font-size: 14px; padding: 8px; }}
    input, select, textarea {{ border: 1px solid #ccc; border-radius: 6px; width: 100%; box-sizing: border-box; }}
    textarea {{ min-height: 96px; resize: vertical; }}
    .col {{ flex: 1 1 220px; }}
    button {{ border: 0; border-radius: 6px; background: #1368ce; color: #fff; cursor: pointer; }}
    pre {{ background: #111827; color: #e5e7eb; padding: 12px; border-radius: 6px; overflow: auto; }}
    .muted {{ color: #666; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>AutoAI Console</h2>
    <p class="muted">Submit task to local workers and poll task + feedback. Console auth is enabled.</p>
    <div class="row">
      <div class="col">
        <label for="api_key">API Key</label>
        <input id="api_key" type="password" value="{expected_api_key}" />
      </div>
      <div class="col">
        <label for="target">Target</label>
        <select id="target">{options}</select>
      </div>
      <div class="col">
        <label for="sessionid">Session ID (optional)</label>
        <input id="sessionid" type="text" maxlength="77" placeholder="codex:1261596828" />
      </div>
    </div>
    <div class="row">
      <div class="col" style="flex: 1 1 100%;">
        <label for="message">Message</label>
        <textarea id="message" placeholder="Type your request"></textarea>
      </div>
    </div>
    <div class="row">
      <button id="submit_btn">Submit Task</button>
    </div>
    <div class="row">
      <div class="col">
        <label>Status</label>
        <pre id="status_box"></pre>
      </div>
      <div class="col">
        <label>Feedback</label>
        <pre id="feedback_box"></pre>
      </div>
    </div>
  </div>
  <script>
    const statusBox = document.getElementById('status_box');
    const feedbackBox = document.getElementById('feedback_box');
    const submitBtn = document.getElementById('submit_btn');
    let pollingTimer = null;

    function headers() {{
      const key = document.getElementById('api_key').value.trim();
      const out = {{ 'Content-Type': 'application/json' }};
      if (key) out['x-api-key'] = key;
      return out;
    }}

    function render(obj) {{
      try {{ return JSON.stringify(obj, null, 2); }} catch (_e) {{ return String(obj); }}
    }}

    async function fetchTask(taskId) {{
      const resp = await fetch(`/api/tasks/${{taskId}}`, {{ headers: headers() }});
      if (!resp.ok) throw new Error(`task status HTTP ${{resp.status}}`);
      return await resp.json();
    }}

    async function fetchFeedback(taskId) {{
      const resp = await fetch(`/api/feedback?task_id=${{taskId}}&limit=100`, {{ headers: headers() }});
      if (!resp.ok) throw new Error(`feedback HTTP ${{resp.status}}`);
      return await resp.json();
    }}

    async function poll(taskId) {{
      try {{
        const [task, feedback] = await Promise.all([fetchTask(taskId), fetchFeedback(taskId)]);
        statusBox.textContent = render(task);
        feedbackBox.textContent = render(feedback);
      }} catch (err) {{
        statusBox.textContent = String(err);
      }}
    }}

    submitBtn.addEventListener('click', async () => {{
      const target = document.getElementById('target').value.trim();
      const message = document.getElementById('message').value.trim();
      const sessionid = document.getElementById('sessionid').value.trim();
      if (!message) {{
        alert('message is required');
        return;
      }}

      submitBtn.disabled = true;
      try {{
        const body = {{ ai_target: target, message }};
        if (sessionid) body.sessionid = sessionid;
        const resp = await fetch('/api/tasks', {{
          method: 'POST',
          headers: headers(),
          body: JSON.stringify(body),
        }});
        if (!resp.ok) {{
          const text = await resp.text();
          throw new Error(`create task failed: HTTP ${{resp.status}} ${{text}}`);
        }}
        const data = await resp.json();
        statusBox.textContent = render(data);
        if (pollingTimer) clearInterval(pollingTimer);
        await poll(data.task_id);
        pollingTimer = setInterval(() => poll(data.task_id), 2000);
      }} catch (err) {{
        statusBox.textContent = String(err);
      }} finally {{
        submitBtn.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""
        return HTMLResponse(content=html)

    return router
