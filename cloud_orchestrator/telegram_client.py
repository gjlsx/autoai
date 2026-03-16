from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib import parse, request


class TelegramClient:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"

    def get_updates(self, offset: Optional[int], timeout: int) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(f"{self.base}/getUpdates", data=data, method="POST")
        with request.urlopen(req, timeout=max(timeout + 5, 10)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"telegram getUpdates failed: {body}")
        return list(body.get("result", []))

    def send_message(self, chat_id: str, text: str) -> Dict[str, Any]:
        payload = {"chat_id": str(chat_id), "text": text}
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(f"{self.base}/sendMessage", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"telegram sendMessage failed: {body}")
        return body

