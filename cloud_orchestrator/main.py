from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI

from cloud_orchestrator import db
from cloud_orchestrator.api import build_router
from cloud_orchestrator.config import Settings, load_settings
from cloud_orchestrator.telegram_client import TelegramClient
from cloud_orchestrator.telegram_inbound import process_message
from cloud_orchestrator.telegram_outbound import deliver_once


def _extract_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    msg = update.get("message")
    if msg:
        return msg
    edited = update.get("edited_message")
    if edited:
        return edited
    return None


async def inbound_loop(stop_event: asyncio.Event, settings: Settings, tg: TelegramClient) -> None:
    offset: Optional[int] = None
    while not stop_event.is_set():
        try:
            updates = await asyncio.to_thread(
                tg.get_updates,
                offset,
                settings.telegram_get_updates_timeout_sec,
            )
            for update in updates:
                update_id = int(update.get("update_id", 0))
                offset = update_id + 1
                msg = _extract_message(update)
                if not msg:
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                chat = msg.get("chat") or {}
                user = msg.get("from") or {}
                chat_id = str(chat.get("id"))
                user_id = str(user.get("id") or "")
                if chat_id:
                    process_message(settings, tg, chat_id, user_id, text, update_id=update_id)
        except Exception as exc:
            db.insert_system_feedback(settings, None, "cloud_orchestrator", f"inbound loop error: {exc}")
            await asyncio.sleep(max(settings.inbound_poll_interval_sec, 1.0))


async def outbound_loop(stop_event: asyncio.Event, settings: Settings, tg: TelegramClient) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(deliver_once, settings, tg, 20)
        except Exception as exc:
            db.insert_system_feedback(settings, None, "cloud_orchestrator", f"outbound loop error: {exc}")
        await asyncio.sleep(max(settings.outbound_poll_interval_sec, 0.5))


def create_app(settings: Optional[Settings] = None, start_workers: bool = True) -> FastAPI:
    app_settings = settings or load_settings()
    app = FastAPI(title="AutoAI Cloud Orchestrator", version="0.1.0")
    app.include_router(build_router(app_settings))

    if not start_workers:
        return app

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = asyncio.Event()
        tg = TelegramClient(app_settings.telegram_bot_token)
        inbound_task = asyncio.create_task(inbound_loop(stop_event, app_settings, tg))
        outbound_task = asyncio.create_task(outbound_loop(stop_event, app_settings, tg))
        try:
            yield
        finally:
            stop_event.set()
            inbound_task.cancel()
            outbound_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await inbound_task
            with contextlib.suppress(asyncio.CancelledError):
                await outbound_task

    app.router.lifespan_context = lifespan
    return app


def _build_default_app() -> FastAPI:
    try:
        if os.getenv("ORCH_DISABLE_WORKERS", "").strip() in {"1", "true", "yes"}:
            return create_app(start_workers=False)
        return create_app()
    except Exception as exc:
        # Keep module importable for tests/tooling; runtime logs still expose misconfiguration.
        fallback = FastAPI(title="AutoAI Cloud Orchestrator (misconfigured)")

        @fallback.get("/healthz")
        def healthz():
            return {"status": "misconfigured", "detail": str(exc)}

        return fallback


app = _build_default_app()
