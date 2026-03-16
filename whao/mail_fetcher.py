from __future__ import annotations

import argparse
import base64
import email
import html
import imaplib
import json
import poplib
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.header import decode_header
from urllib.error import HTTPError, URLError


CODE_CONTEXT_PATTERNS = [
    re.compile(
        r"(?:验证码|驗證碼|verification code|security code|one[- ]time code|otp)[^0-9]{0,20}(\d{4,8})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{4,8})[^0-9]{0,20}(?:验证码|驗證碼|verification code|security code|one[- ]time code|otp)",
        re.IGNORECASE,
    ),
]


@dataclass(slots=True)
class AccountRecord:
    email: str
    secret: str
    client_id: str | None = None
    refresh_token: str | None = None

    @classmethod
    def from_line(cls, line: str) -> "AccountRecord":
        parts = [item.strip() for item in line.strip().split("----")]
        if len(parts) < 2:
            raise ValueError("账号格式错误，至少需要: 邮箱----密码")
        return cls(
            email=parts[0],
            secret=parts[1],
            client_id=parts[2] if len(parts) >= 3 and parts[2] else None,
            refresh_token=parts[3] if len(parts) >= 4 and parts[3] else None,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="微软邮箱 IMAP/POP3 收件脚本")
    parser.add_argument("--protocol", choices=["imap", "pop3"], default="imap")
    parser.add_argument("--account-file", default="新建 文本文档.txt")
    parser.add_argument("--account-line", default="")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--all", action="store_true", help="IMAP 下拉取全部邮件（默认仅拉取未读）")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--preview-chars", type=int, default=160)
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def load_account_line(account_line: str, account_file: str) -> str:
    if account_line.strip():
        return account_line.strip()
    with open(account_file, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                return raw
    raise ValueError("账号文件为空")


def decode_mime_words(value: str | None) -> str:
    if not value:
        return ""
    chunks: list[str] = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            enc = charset or "utf-8"
            try:
                chunks.append(text.decode(enc, errors="replace"))
            except LookupError:
                chunks.append(text.decode("utf-8", errors="replace"))
        else:
            chunks.append(text)
    return "".join(chunks).strip()


def normalize_text(raw: str) -> str:
    unescaped = html.unescape(raw or "")
    return re.sub(r"\s+", " ", unescaped).strip()


def extract_text(msg: email.message.Message) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")
            lowered = text.lower()
            if content_type == "text/html" or "<html" in lowered or "<!doctype" in lowered:
                text = re.sub(r"<[^>]+>", " ", text)
            parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")
            lowered = text.lower()
            if "<html" in lowered or "<!doctype" in lowered:
                text = re.sub(r"<[^>]+>", " ", text)
            parts.append(text)
    return normalize_text(" ".join(parts))


def extract_codes(subject: str, body: str) -> list[str]:
    text = f"{subject}\n{body}"
    seen: set[str] = set()
    codes: list[str] = []
    for pattern in CODE_CONTEXT_PATTERNS:
        for item in pattern.findall(text):
            if item not in seen:
                seen.add(item)
                codes.append(item)
    return codes[:10]


def parse_mail(raw_bytes: bytes) -> dict:
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    msg = email.message_from_bytes(raw_bytes)
    subject = decode_mime_words(msg.get("Subject", ""))
    sender = decode_mime_words(msg.get("From", ""))
    date = decode_mime_words(msg.get("Date", ""))
    body = extract_text(msg)
    return {
        "subject": subject,
        "from": sender,
        "date": date,
        "body": body,
        "codes": extract_codes(subject, body),
    }


_token_cache: dict[str, tuple[str, float]] = {}
_token_cache_lock = threading.Lock()


def refresh_access_token(account: AccountRecord, timeout: int) -> str:
    if not account.client_id or not account.refresh_token:
        raise RuntimeError("缺少 OAuth2 所需字段: client_id 或 refresh_token")

    cache_key = account.email.lower()
    with _token_cache_lock:
        cached = _token_cache.get(cache_key)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at:
                return token

    payload = urllib.parse.urlencode(
        {
            "client_id": account.client_id,
            "refresh_token": account.refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": "https://login.live.com/oauth20_desktop.srf",
        }
    ).encode("utf-8")
    request = urllib.request.Request("https://login.live.com/oauth20_token.srf", data=payload)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
            data = json.loads(body)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OAuth2 刷新失败: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OAuth2 刷新失败: {exc}") from exc

    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("OAuth2 刷新失败: 响应里没有 access_token")
    expires_in = int(data.get("expires_in", 3600))
    with _token_cache_lock:
        _token_cache[cache_key] = (str(access_token), time.time() + expires_in - 60)
    return str(access_token)


def build_xoauth2(email_address: str, access_token: str) -> bytes:
    return f"user={email_address}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")


def imap_authenticate(client: imaplib.IMAP4_SSL, account: AccountRecord, timeout: int) -> str:
    if account.client_id and account.refresh_token:
        access_token = refresh_access_token(account, timeout=timeout)
        try:
            client.authenticate("XOAUTH2", lambda _: build_xoauth2(account.email, access_token))
            return "xoauth2"
        except imaplib.IMAP4.error:
            pass
    try:
        client.login(account.email, account.secret)
        return "password"
    except imaplib.IMAP4.error as login_error:
        if not account.client_id or not account.refresh_token:
            raise RuntimeError(f"密码登录失败且无 OAuth2 字段: {login_error}") from login_error
        raise RuntimeError(f"OAuth2 与密码登录都失败: {login_error}") from login_error


def pop3_password_authenticate(client: poplib.POP3_SSL, account: AccountRecord) -> str:
    client.user(account.email)
    client.pass_(account.secret)
    return "password"


def pop3_oauth2_authenticate(client: poplib.POP3_SSL, account: AccountRecord, timeout: int) -> str:
    access_token = refresh_access_token(account, timeout=timeout)
    xoauth2 = base64.b64encode(build_xoauth2(account.email, access_token)).decode("ascii")
    client._putcmd("AUTH XOAUTH2")
    client._getresp()
    client._putline(xoauth2.encode("ascii"))
    client._getresp()
    return "xoauth2"


def fetch_imap(
    account: AccountRecord,
    host: str,
    port: int,
    limit: int,
    unseen_only: bool,
    timeout: int,
    retries: int,
) -> tuple[list[dict], str]:
    criteria = "UNSEEN" if unseen_only else "ALL"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        client: imaplib.IMAP4_SSL | None = None
        try:
            client = imaplib.IMAP4_SSL(host=host, port=port, timeout=timeout)
            auth_method = imap_authenticate(client, account, timeout=timeout)
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError("IMAP 选择 INBOX 失败")
            status, data = client.search(None, criteria)
            if status != "OK" or not data:
                raise RuntimeError("IMAP 搜索邮件失败")

            mail_ids = data[0].split()
            if limit > 0:
                mail_ids = mail_ids[-limit:]

            messages: list[dict] = []
            for mail_id in reversed(mail_ids):
                status, payload = client.fetch(mail_id, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                raw_mail = b""
                for item in payload:
                    if isinstance(item, tuple) and len(item) > 1:
                        raw_mail = item[1]
                        break
                if not raw_mail:
                    continue
                mail = parse_mail(raw_mail)
                mail["id"] = mail_id.decode("utf-8", errors="ignore")
                messages.append(mail)

            try:
                client.close()
            except Exception:
                pass
            client.logout()
            return messages, auth_method
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass
            if attempt < retries:
                time.sleep(min(2 * attempt, 5))
    raise RuntimeError(f"IMAP 收件失败: {last_error}")


def fetch_pop3(
    account: AccountRecord,
    host: str,
    port: int,
    limit: int,
    timeout: int,
    retries: int,
) -> tuple[list[dict], str]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        client: poplib.POP3_SSL | None = None
        try:
            client = poplib.POP3_SSL(host=host, port=port, timeout=timeout)
            try:
                auth_method = pop3_password_authenticate(client, account)
            except poplib.error_proto as password_error:
                if client is not None:
                    try:
                        client.quit()
                    except Exception:
                        pass
                if not account.client_id or not account.refresh_token:
                    raise RuntimeError(
                        f"POP3 密码登录失败且无 OAuth2 字段: {password_error}"
                    ) from password_error
                client = poplib.POP3_SSL(host=host, port=port, timeout=timeout)
                try:
                    auth_method = pop3_oauth2_authenticate(client, account, timeout=timeout)
                except poplib.error_proto as oauth_error:
                    raise RuntimeError(
                        f"POP3 密码与 OAuth2 登录都失败: {oauth_error}"
                    ) from oauth_error

            total_count, _ = client.stat()
            if limit <= 0:
                start = 1
            else:
                start = max(1, total_count - limit + 1)

            messages: list[dict] = []
            for idx in range(total_count, start - 1, -1):
                _, lines, _ = client.retr(idx)
                raw_mail = b"\r\n".join(lines)
                mail = parse_mail(raw_mail)
                mail["id"] = str(idx)
                messages.append(mail)

            client.quit()
            return messages, auth_method
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass
            if attempt < retries:
                time.sleep(min(2 * attempt, 5))
    raise RuntimeError(f"POP3 收件失败: {last_error}")


class ImapSession:
    """可复用的 IMAP 连接，避免每次轮询都重新 TCP+SSL+认证。"""

    def __init__(self, account: AccountRecord, host: str = "outlook.office365.com",
                 port: int = 993, timeout: int = 20):
        self.account = account
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client: imaplib.IMAP4_SSL | None = None
        self._auth_method: str = ""

    def _connect(self) -> None:
        self._client = imaplib.IMAP4_SSL(host=self.host, port=self.port, timeout=self.timeout)
        self._auth_method = imap_authenticate(self._client, self.account, timeout=self.timeout)

    def _ensure_connected(self) -> None:
        if self._client is not None:
            try:
                self._client.noop()
                return
            except Exception:
                self.close()
        self._connect()

    def fetch_messages(self, limit: int, unseen_only: bool) -> tuple[list[dict], str]:
        self._ensure_connected()
        criteria = "UNSEEN" if unseen_only else "ALL"
        status, _ = self._client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP 选择 INBOX 失败")
        status, data = self._client.search(None, criteria)
        if status != "OK" or not data:
            raise RuntimeError("IMAP 搜索邮件失败")

        mail_ids = data[0].split()
        if limit > 0:
            mail_ids = mail_ids[-limit:]

        messages: list[dict] = []
        for mail_id in reversed(mail_ids):
            status, payload = self._client.fetch(mail_id, "(RFC822)")
            if status != "OK" or not payload:
                continue
            raw_mail = b""
            for item in payload:
                if isinstance(item, tuple) and len(item) > 1:
                    raw_mail = item[1]
                    break
            if not raw_mail:
                continue
            mail = parse_mail(raw_mail)
            mail["id"] = mail_id.decode("utf-8", errors="ignore")
            messages.append(mail)
        return messages, self._auth_method

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def mask_email(email_address: str) -> str:
    if "@" not in email_address:
        return email_address
    name, domain = email_address.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[:2] + "*" * (len(name) - 2)
    return f"{masked_name}@{domain}"


def preview_text(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    cleaned = normalize_text(value)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def print_result(messages: list[dict], preview_chars: int) -> None:
    if not messages:
        print("未获取到邮件")
        return
    for idx, mail in enumerate(messages, start=1):
        print(f"[{idx}] id={mail.get('id', '-')}")
        print(f"    date: {mail.get('date', '')}")
        print(f"    from: {mail.get('from', '')}")
        print(f"    subject: {mail.get('subject', '')}")
        print(f"    codes: {', '.join(mail.get('codes', [])) or '-'}")
        preview = preview_text(mail.get("body", ""), preview_chars)
        if preview:
            print(f"    body_preview: {preview}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()

    account_line = load_account_line(args.account_line, args.account_file)
    account = AccountRecord.from_line(account_line)

    protocol = args.protocol.lower()
    default_host = "outlook.office365.com"
    default_port = 993 if protocol == "imap" else 995
    host = args.host or default_host
    port = args.port or default_port

    if protocol == "imap":
        messages, auth_method = fetch_imap(
            account=account,
            host=host,
            port=port,
            limit=args.limit,
            unseen_only=not args.all,
            timeout=args.timeout,
            retries=max(1, args.retries),
        )
    else:
        messages, auth_method = fetch_pop3(
            account=account,
            host=host,
            port=port,
            limit=args.limit,
            timeout=args.timeout,
            retries=max(1, args.retries),
        )

    print(
        f"收件成功: protocol={protocol.upper()} auth={auth_method} mailbox={mask_email(account.email)} count={len(messages)}"
    )
    print_result(messages, preview_chars=args.preview_chars)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as fh:
            json.dump(messages, fh, ensure_ascii=False, indent=2)
        print(f"已写入 JSON: {args.json_output}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"执行失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
