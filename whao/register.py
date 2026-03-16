"""
OpenAI 批量注册脚本 — API 版 (v4.0 并发)
基于 curl_cffi 的纯 API 注册流程 + IMAP 邮箱验证码获取
支持多线程并发注册 + 反检测措施
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, Callable
from email.utils import parsedate_to_datetime
import time
import random
import os
import re
import json
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

from curl_cffi import requests as cffi_requests

# ─── 将 mail_fetcher 添加到路径 ───
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from mail_fetcher import AccountRecord, ImapSession

# ─── 日志配置 ───
LOG_FILE = os.path.join(SCRIPT_DIR, "registration.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── 配置 ───
DEFAULT_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, "accounts.txt")
ACCOUNT_FILE = os.getenv("ACCOUNT_FILE", DEFAULT_ACCOUNT_FILE)
if not os.path.isabs(ACCOUNT_FILE):
    ACCOUNT_FILE = os.path.join(SCRIPT_DIR, ACCOUNT_FILE)
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
REGISTER_COUNT = int(os.getenv("REGISTER_COUNT", "99999"))
PROXY = os.getenv("PROXY", "")

# ─── 等待时间常量（秒）───
IMAP_TIMEOUT = int(os.getenv("IMAP_TIMEOUT", "40"))
CODE_MAIL_MAX_AGE_SECONDS = int(os.getenv("CODE_MAIL_MAX_AGE_SECONDS", "900"))
RESEND_CODE_EVERY_SECONDS = int(os.getenv("RESEND_CODE_EVERY_SECONDS", "20"))

# ─── 稳定性常量 ───
MAX_CONSECUTIVE_FAILS = 5
MAX_RETRIES_PER_ACCOUNT = 2
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "20"))
EXPECTED_CODE_LENGTH = 6
IMAP_UNSEEN_LIMIT = 20
IMAP_ALL_LIMIT = 40

# ─── 随机浏览器指纹生成 ───
# impersonate → (浏览器大版本号, 构建号基数)
_CHROME_PROFILES = {
    "chrome120": (120, 6099), "chrome123": (123, 6312), "chrome124": (124, 6367),
    "chrome131": (131, 6778), "chrome133a": (133, 6943), "chrome136": (136, 7103),
    "chrome142": (142, 7451),
}
_EDGE_PROFILES = {
    "edge99": (99, 1150), "edge101": (101, 1210),
}
_FIREFOX_PROFILES = {
    "firefox133": 133, "firefox135": 135, "firefox144": 144,
}
_SAFARI_PROFILES = {
    "safari15_3": "15.3", "safari15_5": "15.5",
    "safari17_0": "17.0", "safari18_0": "18.0",
}
_WIN_NT_VERSIONS = ["10.0", "10.0", "10.0", "10.0", "11.0"]
_MAC_VERSIONS = [
    "10_15_7", "11_6_1", "12_7_4", "13_6_3", "14_2_1", "14_4_1", "14_7_2", "15_1_1",
]
_ACCEPT_LANGS = [
    "en-US,en;q=0.9", "en-US,en;q=0.8", "en-GB,en;q=0.9,en-US;q=0.8",
    "en-US,en;q=0.9,zh-CN;q=0.8", "en,en-US;q=0.9", "en-US,en;q=0.9,ja;q=0.8",
    "en-US,en;q=0.9,de;q=0.8", "en-US,en;q=0.9,fr;q=0.8", "en-US,en;q=0.9,ko;q=0.8",
    "en-US,en;q=0.9,es;q=0.8", "en-US,en;q=0.9,pt;q=0.8",
]
# Chrome Not-A-Brand 变体（不同版本格式不同）
_NOT_BRANDS = [
    '"Not_A Brand";v="8"', '"Not-A.Brand";v="99"', '"Not/A)Brand";v="24"',
    '"Not)A;Brand";v="99"', '"Not;A=Brand";v="8"',
]
# 浏览器类型权重：Chrome 最常见
_BROWSER_WEIGHTS = [("chrome", 55), ("edge", 15), ("firefox", 15), ("safari", 15)]
_BROWSER_POOL = [b for b, w in _BROWSER_WEIGHTS for _ in range(w)]


def _generate_fingerprint() -> tuple[str, dict[str, str]]:
    """为单个账号生成完全随机的浏览器指纹。返回 (impersonate值, 额外headers)"""
    browser = random.choice(_BROWSER_POOL)
    lang = random.choice(_ACCEPT_LANGS)

    if browser == "chrome":
        imp, (major, base_build) = random.choice(list(_CHROME_PROFILES.items()))
        patch = random.randint(0, 250)
        sub = random.randint(0, 99)
        not_brand = random.choice(_NOT_BRANDS)
        if random.random() < 0.7:
            win = random.choice(_WIN_NT_VERSIONS)
            ua = f"Mozilla/5.0 (Windows NT {win}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{base_build}.{patch} Safari/537.36"
            platform = '"Windows"'
        else:
            mac = random.choice(_MAC_VERSIONS)
            ua = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{base_build}.{patch} Safari/537.36"
            platform = '"macOS"'
        headers = {
            "User-Agent": ua, "Accept-Language": lang,
            "sec-ch-ua": f'"Chromium";v="{major}", "Google Chrome";v="{major}", {not_brand}',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": platform,
        }

    elif browser == "edge":
        imp, (major, edge_base) = random.choice(list(_EDGE_PROFILES.items()))
        chrome_build = random.randint(4800, 5200)
        chrome_patch = random.randint(0, 120)
        edge_patch = random.randint(0, 80)
        not_brand = random.choice(_NOT_BRANDS)
        win = random.choice(_WIN_NT_VERSIONS)
        ua = (f"Mozilla/5.0 (Windows NT {win}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              f"Chrome/{major}.0.{chrome_build}.{chrome_patch} Safari/537.36 Edg/{major}.0.{edge_base}.{edge_patch}")
        headers = {
            "User-Agent": ua, "Accept-Language": lang,
            "sec-ch-ua": f'"Chromium";v="{major}", "Microsoft Edge";v="{major}", {not_brand}',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
        }

    elif browser == "firefox":
        imp, major = random.choice(list(_FIREFOX_PROFILES.items()))
        if random.random() < 0.7:
            win = random.choice(_WIN_NT_VERSIONS)
            ua = f"Mozilla/5.0 (Windows NT {win}; Win64; x64; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"
        else:
            mac = random.choice(_MAC_VERSIONS)
            ua = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac}; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"
        headers = {"User-Agent": ua, "Accept-Language": lang}

    else:  # safari
        imp, ver = random.choice(list(_SAFARI_PROFILES.items()))
        mac = random.choice(_MAC_VERSIONS)
        ua = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{ver} Safari/605.1.15"
        headers = {"User-Agent": ua, "Accept-Language": lang}

    return imp, headers


# ─── 预编译正则 ───
_RE_6DIGIT = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_RE_IP = re.compile(r"^ip=(.+)$", re.MULTILINE)
_RE_LOC = re.compile(r"^loc=(.+)$", re.MULTILINE)

# ─── 随机名字池（200名 × 200姓 = 40000 基础组合，加中间名后 > 百万） ───
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory",
    "Debra", "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack",
    "Catherine", "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron",
    "Ruth", "Jose", "Julie", "Adam", "Olivia", "Nathan", "Joyce", "Henry", "Virginia",
    "Peter", "Victoria", "Zachary", "Kelly", "Douglas", "Lauren", "Harold", "Christina",
    "Carl", "Joan", "Arthur", "Evelyn", "Gerald", "Judith", "Roger", "Megan",
    "Keith", "Andrea", "Jeremy", "Cheryl", "Terry", "Hannah", "Lawrence", "Jacqueline",
    "Sean", "Martha", "Christian", "Gloria", "Albert", "Teresa", "Joe", "Ann",
    "Ethan", "Sara", "Austin", "Madison", "Jesse", "Frances", "Willie", "Kathryn",
    "Billy", "Janice", "Bryan", "Jean", "Bruce", "Abigail", "Jordan", "Alice",
    "Ralph", "Judy", "Roy", "Sophia", "Noah", "Grace", "Dylan", "Denise", "Eugene",
    "Amber", "Wayne", "Doris", "Elijah", "Marilyn", "Russell", "Danielle", "Vincent",
    "Beverly", "Philip", "Isabella", "Bobby", "Theresa", "Johnny", "Diana", "Bradley",
    "Natalie", "Logan", "Brittany", "Craig", "Charlotte", "Alan", "Marie",
    "Derrick", "Kayla", "Victor", "Alexis", "Shawn", "Lori",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker",
    "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales", "Murphy",
    "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey",
    "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson",
    "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz",
    "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long",
    "Ross", "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell", "Sullivan",
    "Bell", "Coleman", "Butler", "Henderson", "Barnes", "Gonzales", "Fisher",
    "Vasquez", "Simmons", "Graham", "Murray", "Ford", "Castro", "Marshall",
    "Owens", "Harrison", "Fernandez", "McDonald", "Woods", "Washington", "Kennedy",
    "Wells", "Vargas", "Henry", "Chen", "Freeman", "Webb", "Tucker", "Guzman",
    "Burns", "Crawford", "Olson", "Simpson", "Porter", "Hunter", "Gordon", "Mendez",
    "Silva", "Shaw", "Snyder", "Mason", "Dixon", "Munoz", "Hunt", "Hicks", "Holmes",
    "Palmer", "Wagner", "Black", "Robertson", "Boyd", "Rose", "Stone", "Salazar",
    "Fox", "Warren", "Mills", "Meyer", "Rice", "Schmidt", "Garza", "Daniels",
    "Ferguson", "Nichols", "Stephens", "Soto", "Weaver", "Ryan", "Gardner", "Payne",
    "Grant", "Dunn", "Kelley", "Spencer", "Hawkins", "Arnold", "Pierce", "Vazquez",
    "Hansen", "Peters", "Santos", "Hart", "Bradley", "Knight", "Elliott", "Cunningham",
    "Duncan", "Armstrong", "Hudson", "Carroll", "Lane", "Riley", "Andrews", "Alvarado",
    "Ray", "Delgado", "Berry", "Perkins", "Hoffman", "Johnston", "Matthews", "Pena",
    "Richards", "Contreras", "Willis", "Carpenter", "Lawrence", "Sandoval", "Guerrero",
    "George", "Chapman", "Rios", "Estrada", "Ortega", "Watkins", "Greene", "Barrett",
    "Medina", "Rowe", "Chambers", "Dawson", "Park",
]

MIDDLE_INITIALS = list("ABCDEFGHJKLMNPRSTW")

# ─── OAuth 常量 ───
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_CALLBACK_PORT = 1455
DEFAULT_REDIRECT_URI = f"http://localhost:{DEFAULT_CALLBACK_PORT}/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


# ========== 工具函数 ==========

def load_accounts(filepath: str) -> list[AccountRecord]:
    """从邮箱文件加载所有账号"""
    accounts = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                accounts.append(AccountRecord.from_line(line))
            except ValueError as e:
                log.warning(f"跳过格式错误行: {e}")
    return accounts


def load_done_emails(results_dir: str) -> set[str]:
    """扫描 results 目录，加载已注册邮箱集合"""
    done = set()
    if not os.path.isdir(results_dir):
        return done
    for fname in os.listdir(results_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(results_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            email_addr = data.get("email", "").lower()
            if email_addr:
                done.add(email_addr)
        except Exception:
            pass
    return done


def save_account_result(results_dir: str, email_addr: str, config: dict) -> str:
    """将单个账号结果保存为独立 JSON 文件"""
    os.makedirs(results_dir, exist_ok=True)
    filepath = os.path.join(results_dir, f"{email_addr}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return filepath


def generate_name() -> str:
    """随机生成全名（~30%概率带中间名首字母，增加组合数）"""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    if random.random() < 0.3:
        mid = random.choice(MIDDLE_INITIALS)
        return f"{first} {mid}. {last}"
    return f"{first} {last}"


def generate_birthday() -> str:
    """随机生成一个合理的生日 (YYYY-MM-DD)，年龄在 18-45 之间"""
    year = random.randint(1981, 2007)
    month = random.randint(1, 12)
    max_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
               7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[month]
    day = random.randint(1, max_day)
    return f"{year}-{month:02d}-{day:02d}"


def format_exception(exc: Exception) -> str:
    """格式化异常用于日志"""
    err_name = type(exc).__name__
    err_text = str(exc).strip()
    if not err_text:
        err_text = repr(exc)
    first_line = err_text.splitlines()[0][:180]
    return f"[{err_name}] {first_line}"


# ========== OAuth / Token ==========

def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(
    url: str, data: Dict[str, str], timeout: int = 30,
    session: cffi_requests.Session | None = None,
) -> Dict[str, Any]:
    """POST form 数据，优先使用 session（支持代理），否则回退 urllib"""
    if session is not None:
        resp = session.post(
            url, data=data, timeout=timeout,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"token exchange failed: {resp.status_code}: {resp.text[:500]}")
        return resp.json()
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}") from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(
    *, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE,
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)
    params = {
        "client_id": CLIENT_ID, "response_type": "code",
        "redirect_uri": redirect_uri, "scope": scope,
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "prompt": "login",
        "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(auth_url=auth_url, state=state, code_verifier=code_verifier, redirect_uri=redirect_uri)


def submit_callback_url(
    *, callback_url: str, expected_state: str, code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    session: cffi_requests.Session | None = None,
) -> str:
    """解析回调 URL 并交换 token"""
    candidate = callback_url.strip()
    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    code = (query.get("code", [""])[0] or "").strip()
    state = (query.get("state", [""])[0] or "").strip()
    error = (query.get("error", [""])[0] or "").strip()
    error_desc = (query.get("error_description", [""])[0] or "").strip()

    if error:
        raise RuntimeError(f"oauth error: {error}: {error_desc}")
    if not code:
        raise ValueError("callback url missing ?code=")
    if state != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier,
    }, session=session)

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email_addr = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    config = {
        "id_token": id_token, "access_token": access_token,
        "refresh_token": refresh_token, "account_id": account_id,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "email": email_addr, "type": "codex",
        "expired": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))),
    }
    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


# ========== IMAP 验证码 ==========

def parse_mail_timestamp(date_text: str) -> float | None:
    """解析邮件日期为 epoch 秒"""
    if not date_text:
        return None
    try:
        dt = parsedate_to_datetime(date_text)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_openai_mail(sender: str, subject: str, body: str) -> bool:
    """判断邮件是否来自 OpenAI 相关验证码"""
    haystack = f"{sender}\n{subject}\n{body}".lower()
    return any(keyword in haystack for keyword in ("openai", "chatgpt", "verification code", "验证码"))


def extract_6digit_codes(subject: str, body: str, fallback_codes: list) -> list[tuple[str, str]]:
    """提取 6 位验证码候选"""
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    subject_match = _RE_6DIGIT.search(subject or "")
    if subject_match:
        code = subject_match.group(1)
        seen.add(code)
        candidates.append((code, "subject"))

    body_match = _RE_6DIGIT.search(body or "")
    if body_match:
        code = body_match.group(1)
        if code not in seen:
            seen.add(code)
            candidates.append((code, "body"))

    for code in fallback_codes:
        if isinstance(code, str) and len(code) == EXPECTED_CODE_LENGTH and code.isdigit() and code not in seen:
            seen.add(code)
            candidates.append((code, "codes"))
    return candidates


def pick_best_oai_code(
    messages: list[dict],
    seen_codes: set[str],
    min_mail_epoch: float,
) -> tuple[str | None, str]:
    """从邮件列表中按时间顺序选出首个可用验证码"""
    for mail in messages:
        sender = str(mail.get("from", ""))
        subject = str(mail.get("subject", ""))
        body = str(mail.get("body", ""))
        if not is_openai_mail(sender, subject, body):
            continue

        mail_ts = parse_mail_timestamp(str(mail.get("date", "")))
        if mail_ts is not None and mail_ts < min_mail_epoch:
            continue

        for code, source in extract_6digit_codes(subject, body, mail.get("codes", [])):
            if code in seen_codes:
                continue
            return code, source

    return None, ""


def get_oai_code_imap(
    account: AccountRecord,
    timeout_seconds: int = IMAP_TIMEOUT,
    *,
    seen_codes: set[str] | None = None,
    min_mail_epoch: float | None = None,
    resend_otp_fn: Callable[[], bool] | None = None,
) -> str:
    """通过 IMAP 轮询获取 OpenAI 验证码（使用持久连接）"""
    log.info("  等待 OpenAI 验证码 (IMAP)...")
    start = time.time()
    seen = seen_codes if seen_codes is not None else set()
    min_epoch = min_mail_epoch if min_mail_epoch is not None else (start - CODE_MAIL_MAX_AGE_SECONDS)
    poll_intervals = [3, 3, 5, 5, 8, 8, 10]
    poll_idx = 0
    last_resend_ts = 0.0

    with ImapSession(account, host="outlook.office365.com", port=993, timeout=20) as imap:
        while time.time() - start < timeout_seconds:
            elapsed = int(time.time() - start)
            if poll_idx == 0 or poll_idx % 3 == 0:
                log.info(f"  IMAP 轮询中... 已等待 {elapsed}s")
            try:
                # poll_idx < 2 时只查 UNSEEN；之后查 ALL（已包含 UNSEEN，无需双查）
                if poll_idx < 2:
                    messages, auth_method = imap.fetch_messages(
                        limit=IMAP_UNSEEN_LIMIT, unseen_only=True,
                    )
                else:
                    messages, auth_method = imap.fetch_messages(
                        limit=IMAP_ALL_LIMIT, unseen_only=False,
                    )
                code, source = pick_best_oai_code(messages, seen, min_epoch)
                if code:
                    seen.add(code)
                    scope = "UNSEEN" if poll_idx < 2 else "ALL"
                    log.info(f"  验证码: {code} (from {source}, auth={auth_method}, scope={scope})")
                    return code
            except Exception as e:
                log.warning(f"  IMAP 查询出错: {e}")

            elapsed_now = time.time() - start
            if resend_otp_fn is not None and elapsed_now >= 20 and elapsed_now - last_resend_ts >= RESEND_CODE_EVERY_SECONDS:
                try:
                    if resend_otp_fn():
                        last_resend_ts = elapsed_now
                        log.info("  已重新发送 OTP")
                except Exception:
                    pass

            interval = poll_intervals[min(poll_idx, len(poll_intervals) - 1)]
            poll_idx += 1
            time.sleep(interval)

    raise TimeoutError(f"等待验证码超时 ({timeout_seconds}s)")


# ========== API 注册流程 ==========

def register(
    email_addr: str,
    mail_account: AccountRecord,
    proxy: str = "",
    used_codes: set[str] | None = None,
) -> str:
    """通过 API 注册一个 OpenAI 账号（新流程）"""
    log.info(f"\n{'='*60}")
    log.info(f"开始注册: {email_addr}")
    log.info(f"{'='*60}")

    # 1) 创建 curl_cffi 会话（完全随机浏览器指纹）
    proxies = {"http": proxy, "https": proxy} if proxy else None
    fingerprint, fp_headers = _generate_fingerprint()
    s = cffi_requests.Session(proxies=proxies, impersonate=fingerprint)
    s.headers.update(fp_headers)
    log.info(f"  [{email_addr}] 指纹: {fingerprint} | UA: {fp_headers['User-Agent'][:80]}")

    try:
        # 2) 检查 IP（可选，有代理时检查）
        if proxy:
            try:
                trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10).text
                ip_re = _RE_IP.search(trace)
                loc_re = _RE_LOC.search(trace)
                ip = ip_re.group(1) if ip_re else "unknown"
                loc = loc_re.group(1) if loc_re else "unknown"
                log.info(f"  IP: {ip}, Location: {loc}")
                if loc in ("CN", "HK"):
                    raise RuntimeError("代理IP在中国大陆或香港，请更换代理")
            except RuntimeError:
                raise
            except Exception as e:
                log.warning(f"  IP检查失败（继续）: {e}")

        # 3) 生成 OAuth URL 并访问
        oauth = generate_oauth_url()
        log.info("  OAuth URL 已生成")

        resp = s.get(oauth.auth_url, timeout=30)
        log.info(f"  [{email_addr}] GET auth URL: {resp.status_code}")

        did = s.cookies.get("oai-did")
        if not did:
            log.warning(f"  [{email_addr}] 未获取到 oai-did cookie，尝试继续...")
        else:
            log.info(f"  [{email_addr}] oai-did: {did}")

        # 反检测：模拟用户操作间隔
        time.sleep(random.uniform(0.5, 1.5))

        # 4) 获取 sentinel token（不走会话/代理，与新流程一致）
        sen_req_body = json.dumps({"p": "", "id": did or "", "flow": "authorize_continue"})
        sen_resp = cffi_requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            timeout=15,
        )
        log.info(f"  Sentinel: {sen_resp.status_code}")
        if sen_resp.status_code != 200:
            log.error(f"  [{email_addr}] Sentinel 响应: {sen_resp.text[:500]}")
            raise RuntimeError(f"获取 sentinel token 失败: HTTP {sen_resp.status_code}")
        sen_token = sen_resp.json()["token"]
        sentinel = json.dumps({"p": "", "t": "", "c": sen_token, "id": did or "", "flow": "authorize_continue"})

        # 反检测：模拟用户操作间隔
        time.sleep(random.uniform(0.5, 1.5))

        # 5) 提交邮箱注册
        signup_body = json.dumps({"username": {"value": email_addr, "kind": "email"}, "screen_hint": "signup"})
        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
            timeout=30,
        )
        log.info(f"  Signup: {signup_resp.status_code}")
        if signup_resp.status_code != 200:
            log.error(f"  [{email_addr}] Signup 响应: {signup_resp.text[:500]}")
            raise RuntimeError(f"Signup 失败: HTTP {signup_resp.status_code}")

        # 反检测：模拟用户操作间隔
        time.sleep(random.uniform(0.5, 1.5))

        # 6) 发送 OTP 验证码到邮箱
        otp_resp = s.post(
            "https://auth.openai.com/api/accounts/passwordless/send-otp",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
            timeout=30,
        )
        log.info(f"  Send OTP: {otp_resp.status_code}")
        if otp_resp.status_code != 200:
            log.error(f"  [{email_addr}] OTP 响应: {otp_resp.text[:500]}")
            raise RuntimeError(f"Send OTP 失败: HTTP {otp_resp.status_code}")

        # 7) 通过 IMAP 获取验证码（保留旧流程的邮箱管理系统）
        def resend_otp() -> bool:
            try:
                r = s.post(
                    "https://auth.openai.com/api/accounts/passwordless/send-otp",
                    headers={
                        "referer": "https://auth.openai.com/create-account/password",
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    timeout=30,
                )
                return r.status_code == 200
            except Exception:
                return False

        code_ready_at = time.time() - 20
        code = get_oai_code_imap(
            mail_account,
            seen_codes=used_codes,
            min_mail_epoch=code_ready_at,
            resend_otp_fn=resend_otp,
        )
        log.info(f"  获取到验证码: {code}")

        # 8) 验证 OTP
        code_body = json.dumps({"code": code})
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
            timeout=30,
        )
        log.info(f"  Validate OTP: {code_resp.status_code}")
        if code_resp.status_code != 200:
            log.error(f"  [{email_addr}] 验证码验证响应: {code_resp.text[:500]}")
            raise RuntimeError(f"验证码验证失败: HTTP {code_resp.status_code}")

        # 反检测：模拟用户操作间隔
        time.sleep(random.uniform(0.5, 1.5))

        # 9) 创建账号（随机姓名 + 生日）
        name = generate_name()
        birthday = generate_birthday()
        create_body = json.dumps({"name": name, "birthdate": birthday})
        create_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_body,
            timeout=30,
        )
        log.info(f"  Create account: {create_resp.status_code} (name={name}, birthday={birthday})")
        if create_resp.status_code != 200:
            log.error(f"  [{email_addr}] 创建账号响应: {create_resp.text[:500]}")
            raise RuntimeError(f"创建账号失败: HTTP {create_resp.status_code}")

        # 反检测：模拟用户操作间隔
        time.sleep(random.uniform(0.5, 1.5))

        # 10) 从 cookie 获取 workspace_id（BUG-5: 增加错误处理）
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            raise RuntimeError("未获取到 oai-client-auth-session cookie")

        try:
            cookie_parts = auth_cookie.split(".")
            pad = "=" * ((4 - len(cookie_parts[0]) % 4) % 4)
            auth_data = base64.b64decode(cookie_parts[0] + pad)
            auth_json = json.loads(auth_data)
            workspaces = auth_json.get("workspaces")
            if not workspaces or not isinstance(workspaces, list):
                raise RuntimeError(f"cookie 中无 workspaces 数据: {list(auth_json.keys())}")
            workspace_id = workspaces[0].get("id")
            if not workspace_id:
                raise RuntimeError(f"workspace 缺少 id 字段: {workspaces[0]}")
        except (KeyError, IndexError, json.JSONDecodeError, Exception) as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"解析 oai-client-auth-session cookie 失败: {e}") from e
        log.info(f"  Workspace ID: {workspace_id}")

        # 11) 选择 workspace
        select_body = json.dumps({"workspace_id": workspace_id})
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
            timeout=30,
        )
        log.info(f"  Select workspace: {select_resp.status_code}")
        if select_resp.status_code != 200:
            log.error(f"  选择 workspace 响应: {select_resp.text[:500]}")
            raise RuntimeError(f"选择 workspace 失败: HTTP {select_resp.status_code}")

        continue_url = select_resp.json()["continue_url"]

        # 12) 跟随重定向获取回调 URL
        callback_url = None
        url = continue_url
        for step in range(10):
            redir_resp = s.get(url, allow_redirects=False, timeout=30)
            location = redir_resp.headers.get("Location")
            if not location:
                raise RuntimeError(f"重定向步骤 {step + 1} 未返回 Location header")
            if "localhost" in location and "/auth/callback" in location:
                callback_url = location
                break
            url = location

        if not callback_url:
            raise RuntimeError("重定向次数过多，未找到回调 URL")
        log.info("  回调 URL 已获取")

        # 13) 交换 token（BUG-1: 通过 session 走代理）
        result = submit_callback_url(
            callback_url=callback_url,
            expected_state=oauth.state,
            code_verifier=oauth.code_verifier,
            redirect_uri=oauth.redirect_uri,
            session=s,
        )
        log.info("  注册成功!")
        return result
    finally:
        # BUG-4: 确保 session 关闭
        s.close()


# ========== 主循环 ==========

def _register_one(
    account: AccountRecord,
    index: int,
    total: int,
    proxy: str,
    *,
    stats_lock: threading.Lock,
    stats: dict,
    initial_delay: float = 0.0,
) -> tuple[bool, float, str]:
    """单个账号的注册逻辑（含重试），线程安全。返回 (success, elapsed, email)"""
    # 反检测：线程内部交错启动，替代主线程阻塞式提交
    if initial_delay > 0:
        log.info(f"  [{account.email}] 等待 {initial_delay:.1f}s 后开始...")
        time.sleep(initial_delay)

    # 延迟后再检查是否应取消（连续失败过多）
    with stats_lock:
        if stats["consecutive_fails"] >= MAX_CONSECUTIVE_FAILS:
            log.warning(f"  [{account.email}] 连续失败次数过多，跳过注册")
            return False, 0.0, account.email

    account_start = time.time()
    used_codes: set[str] = set()
    log.info(f"\n[{index}/{total}] 开始注册 {account.email}")

    success = False
    for attempt in range(1, MAX_RETRIES_PER_ACCOUNT + 1):
        if attempt > 1:
            log.info(f"  [{account.email}] 第 {attempt} 次重试...")
            time.sleep(3)

        try:
            config_json = register(account.email, account, proxy, used_codes)
            elapsed = time.time() - account_start

            config = json.loads(config_json)
            config["email"] = account.email
            config["register_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            config["elapsed_seconds"] = round(elapsed, 1)

            fpath = save_account_result(RESULTS_DIR, account.email, config)
            success = True

            with stats_lock:
                stats["success"] += 1
                stats["consecutive_fails"] = 0
                stats["timings"].append(elapsed)
                cur_success = stats["success"]
                cur_fail = stats["fail"]

            log.info(f"  [{account.email}] 耗时: {elapsed:.1f} 秒")
            log.info(f"  [{account.email}] 已保存: {fpath}")
            log.info(f"  [{account.email}] 进度: {cur_success} 成功 / {cur_fail} 失败")
            break

        except Exception as e:
            short_err = format_exception(e)
            log.warning(f"  [{account.email}] 尝试 {attempt} 失败: {short_err}", exc_info=True)

    if not success:
        elapsed = time.time() - account_start
        with stats_lock:
            stats["fail"] += 1
            stats["consecutive_fails"] += 1
            stats["timings"].append(elapsed)
            consec = stats["consecutive_fails"]

        log.error(f"  [{account.email}] 注册失败（已重试 {MAX_RETRIES_PER_ACCOUNT} 次）")
        log.info(f"  [{account.email}] 耗时: {elapsed:.1f} 秒")

        if consec >= MAX_CONSECUTIVE_FAILS:
            log.error(f"\n连续失败 {consec} 次，将取消剩余任务！")

    return success, time.time() - account_start, account.email


def main():
    log.info("=" * 60)
    log.info("  OpenAI 批量注册 — API 版 (v4.0 并发)")
    log.info("=" * 60)

    total_start = time.time()

    # 加载邮箱
    if not os.path.isfile(ACCOUNT_FILE):
        log.error(f"账号文件不存在: {ACCOUNT_FILE}")
        return

    accounts = load_accounts(ACCOUNT_FILE)
    log.info(f"账号文件: {ACCOUNT_FILE}")
    log.info(f"加载了 {len(accounts)} 个邮箱账号")

    done_emails = load_done_emails(RESULTS_DIR)
    log.info(f"已注册 {len(done_emails)} 个邮箱")

    pending = [a for a in accounts if a.email.lower() not in done_emails]
    log.info(f"待注册 {len(pending)} 个邮箱")

    if not pending:
        log.info("没有待注册的邮箱!")
        return

    to_register = pending[:REGISTER_COUNT]
    total = len(to_register)
    log.info(f"本次注册 {total} 个邮箱 (并发数: {MAX_WORKERS})")

    proxy = PROXY
    if proxy:
        log.info(f"使用代理: {proxy}")
    else:
        log.info("未配置代理，直连模式")

    # 线程安全的统计计数器
    stats_lock = threading.Lock()
    stats = {"success": 0, "fail": 0, "consecutive_fails": 0, "timings": []}

    # 并发执行
    futures: dict[Future, str] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 立即提交所有任务，交错延迟在工作线程内部执行
        # 同一波次（MAX_WORKERS 个）内的任务按位置递增延迟，实现反检测
        for i, account in enumerate(to_register, 1):
            wave_position = (i - 1) % MAX_WORKERS
            initial_delay = wave_position * random.uniform(1.5, 3.0) if wave_position > 0 else 0

            future = executor.submit(
                _register_one, account, i, total, proxy,
                stats_lock=stats_lock, stats=stats,
                initial_delay=initial_delay,
            )
            futures[future] = account.email

        # 收集结果
        for future in as_completed(futures):
            email_addr = futures[future]
            try:
                success, elapsed, _ = future.result()
            except Exception as e:
                log.error(f"  [{email_addr}] 线程异常: {format_exception(e)}")

    total_elapsed = time.time() - total_start
    timings = stats["timings"]
    success_count = stats["success"]
    fail_count = stats["fail"]

    log.info(f"\n{'='*60}")
    log.info(f"  注册汇总")
    log.info(f"{'='*60}")
    log.info(f"  成功: {success_count}")
    log.info(f"  失败: {fail_count}")
    if timings:
        log.info(f"  平均耗时: {sum(timings)/len(timings):.1f} 秒/账号")
    log.info(f"  并发数: {MAX_WORKERS}")
    log.info(f"  总耗时: {total_elapsed:.1f} 秒 ({total_elapsed/60:.1f} 分钟)")
    log.info(f"  结果目录: {RESULTS_DIR}")
    log.info(f"  日志文件: {LOG_FILE}")


if __name__ == "__main__":
    main()
