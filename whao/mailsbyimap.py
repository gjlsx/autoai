import imaplib
import email
from email.header import decode_header
import requests

# 1. 配置你的數據
EMAIL = ""
CLIENT_ID = ""
REFRESH_TOKEN = ""
# 填入完整的刷新令牌

# 2. 可選：如果有 tk，會自動提取並覆蓋上面的三個變量
# tk 格式: email----password----client_id----refresh_token
tk = "NicholasSmith3539@hotmail.com----rsbtzw91142----9e5f94bc-e8a4-4e73-b8be-63364c29d753----M.C548_BAY.0.U.-CpM7mS2aJXscJCoM*CSohJD0R**BkZMT6nZDuhr853dmWeqYzW4ZDTgKchTso3aot1mIbMEzFpOV!CLYwbfV39nMUubZRPtHQ3!pCzTDC1IP8GPpbmbsKaFAW5sodBz*WlAW84YVDKABiBfqNAhEL9TfU44S55jk8JQO6JynEZeelLKFQ!vEop7d*PCE8jh4bT!JpLmElZ2HnVCTKr*eWfZYKSKDmDCJzf47WoJ966Zau7y9Ew5sVbzyHxNhbiy4bToD7G6H6w0!ss!DEMhm4IhbAVDQXMqgmU3eEZ27Ci550yliR0ILS9qLZ*IT4Dm7!M*hKJZxOPnlWoOlQHi2ldKwtTpjBJP*pZwMBE*kuRqIu6AbvBfqrlrkfmqw2Nj4kESeEO4oe09Zb77h9*WFwaejZfqm7fg1HqWWwtU2!d6z9Q8cTudps9qzyWR2KY*SbSCDkWbM1QYa90S6*igwX34$"


def tk_1to3(tk_value):
    """1to3: 從 tk 提取 (email, client_id, refresh_token)。"""
    parts = [p.strip() for p in tk_value.split("----")]
    if len(parts) >= 4:
        email, _password, client_id, refresh_token = parts[:4]
    elif len(parts) == 3:
        email, client_id, refresh_token = parts
    else:
        raise ValueError(
            "tk 格式錯誤，請使用 email----client_id----refresh_token "
            "或 email----password----client_id----refresh_token"
        )
    return email, client_id, refresh_token


if tk.strip():
    EMAIL, CLIENT_ID, REFRESH_TOKEN = tk_1to3(tk)


def get_access_token(client_id, refresh_token):
    """使用刷新令牌獲取臨時 access_token"""
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
    }
    res = requests.post(url, data=payload)
    return res.json().get("access_token")

def generate_auth_string(user, token):
    """生成微軟要求的 XOAUTH2 認證字符串"""
    auth_string = f"user={user}\x01auth=Bearer {token}\x01\x01"
    # imaplib.authenticate 會自動做 base64，這裡必須返回原始 bytes
    return auth_string.encode("utf-8")


def decode_mime_subject(raw_subject):
    """解碼 Subject 標題，支持多段與多編碼。"""
    if not raw_subject:
        return "(No Subject)"

    chunks = []
    for text, charset in decode_header(raw_subject):
        if isinstance(text, bytes):
            enc = charset or "utf-8"
            try:
                chunks.append(text.decode(enc, errors="replace"))
            except LookupError:
                chunks.append(text.decode("utf-8", errors="replace"))
        else:
            chunks.append(text)

    subject = "".join(chunks).strip()
    return subject or "(No Subject)"


def login_imap():
    access_token = get_access_token(CLIENT_ID, REFRESH_TOKEN)
    if not access_token:
        print("ERROR: cannot get access token")
        return

    # 連接伺服器
    mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    
    try:
        # 使用 XOAUTH2 方式登入
        mail.authenticate('XOAUTH2', lambda x: generate_auth_string(EMAIL, access_token))
        print(f"OK: login success for {EMAIL}")
        
        # 選擇收件箱
        mail.select("INBOX")
        
        # 搜尋郵件 (例如搜尋所有郵件)
        status, messages = mail.search(None, 'ALL')
        mail_ids = messages[0].split()
        print(f"INFO: inbox has {len(mail_ids)} emails")
        
        # 打印最新 10 封郵件標題（由新到舊）
        latest_ids = list(reversed(mail_ids[-10:]))
        print(f"INFO: latest {len(latest_ids)} email subjects")
        for idx, mail_id in enumerate(latest_ids, start=1):
            subject = "(No Subject)"
            res, header_data = mail.fetch(mail_id, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            if res == "OK" and header_data:
                raw_header = b""
                for item in header_data:
                    if isinstance(item, tuple) and len(item) > 1:
                        raw_header = item[1]
                        break
                if raw_header:
                    msg = email.message_from_bytes(raw_header)
                    subject = decode_mime_subject(msg.get("Subject", ""))
            print(f"{idx:02d}. {subject}")

        mail.close()
        mail.logout()
        
    except Exception as e:
        print(f"ERROR: IMAP auth failed: {e}")

if __name__ == "__main__":
    login_imap()
