import json
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path

from bilibili_comment_danmaku.scraper import inspect_cookie_status, load_cookie_file


QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
QR_SESSION_TTL_SECONDS = 180
QR_STATUS_MESSAGES = {
    0: "登录成功",
    86038: "二维码已失效",
    86090: "已扫码，等待确认",
    86101: "等待扫码",
}


@dataclass
class LoginQrSession:
    session_id: str
    qrcode_key: str
    url: str
    created_at: float
    expires_at: float

    def public_payload(self):
        return {
            "session_id": self.session_id,
            "qrcode_key": self.qrcode_key,
            "url": self.url,
            "expires_at": self.expires_at,
            "ttl_seconds": max(int(self.expires_at - time.time()), 0),
        }


class CookieStore:
    def __init__(self, cookie_path, backup_dir=None):
        self.cookie_path = Path(cookie_path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.cookie_path.parent / "backups" / "cookie"

    def load(self):
        if not self.cookie_path.exists():
            return ""
        return load_cookie_file(self.cookie_path)

    def status(self, *, check_remote=True):
        payload = inspect_cookie_status(self.cookie_path, check_remote=check_remote)
        payload["source"] = "managed_file"
        return payload

    def save(self, raw_cookie):
        cookie = normalize_cookie_text(raw_cookie)
        if not cookie:
            raise ValueError("Cookie 内容为空")
        self.backup_existing()
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cookie_path.with_name(f"{self.cookie_path.name}.{secrets.token_hex(4)}.tmp")
        temp_path.write_text(cookie + "\n", encoding="utf-8")
        temp_path.replace(self.cookie_path)
        return self.status(check_remote=True)

    def clear(self):
        self.backup_existing()
        try:
            self.cookie_path.unlink()
        except FileNotFoundError:
            pass
        return self.status(check_remote=False)

    def backup_existing(self):
        if not self.cookie_path.exists():
            return None
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = self.backup_dir / f"cookie-{timestamp}-{secrets.token_hex(3)}.txt"
            backup_path.write_text(self.cookie_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            return backup_path
        except OSError:
            return None


class BilibiliQrLoginService:
    def __init__(self, cookie_store, sessions=None):
        self.cookie_store = cookie_store
        self.sessions = sessions if sessions is not None else {}

    def create_session(self):
        data, _headers = request_json_with_cookies(QR_GENERATE_URL)
        payload = data.get("data") or {}
        qrcode_key = str(payload.get("qrcode_key") or "")
        url = str(payload.get("url") or "")
        if data.get("code") != 0 or not qrcode_key or not url:
            raise RuntimeError(f"二维码生成失败：code={data.get('code')} message={data.get('message')}")

        now = time.time()
        session = LoginQrSession(
            session_id=secrets.token_urlsafe(18),
            qrcode_key=qrcode_key,
            url=url,
            created_at=now,
            expires_at=now + QR_SESSION_TTL_SECONDS,
        )
        self.sessions[session.session_id] = session
        self.prune_expired()
        return session.public_payload()

    def poll(self, session_id):
        self.prune_expired()
        session = self.sessions.get(session_id)
        if not session:
            return {
                "ok": False,
                "status": "expired",
                "code": 86038,
                "message": "二维码会话不存在或已过期",
                "login_url": "",
            }

        query = urllib.parse.urlencode({"qrcode_key": session.qrcode_key})
        payload, headers = request_json_with_cookies(f"{QR_POLL_URL}?{query}")
        data = payload.get("data") or {}
        code = int(data.get("code") if data.get("code") is not None else payload.get("code") or 0)
        message = str(data.get("message") or payload.get("message") or QR_STATUS_MESSAGES.get(code, "等待登录"))
        response = {
            "ok": code == 0,
            "status": qr_status_name(code),
            "code": code,
            "message": message,
            "login_url": str(data.get("url") or ""),
            "expires_at": session.expires_at,
            "ttl_seconds": max(int(session.expires_at - time.time()), 0),
        }

        if code == 0:
            cookie = cookies_from_headers(headers)
            if not cookie:
                response.update(ok=False, status="error", message="登录成功但响应中没有 Cookie")
                return response
            status = self.cookie_store.save(cookie)
            self.sessions.pop(session.session_id, None)
            response["cookie_status"] = status
        elif code == 86038:
            self.sessions.pop(session.session_id, None)
        return response

    def prune_expired(self):
        now = time.time()
        for session_id, session in list(self.sessions.items()):
            if session.expires_at <= now:
                self.sessions.pop(session_id, None)


def normalize_cookie_text(raw_cookie):
    text = str(raw_cookie or "").strip()
    if not text:
        return ""
    cookies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) >= 7 and columns[5] and "bilibili.com" in columns[0]:
            cookies.append(f"{columns[5]}={columns[6]}")
        elif "=" in line and "\t" not in line:
            cookies.append(line.rstrip(";"))
    return "; ".join(cookies).replace("\r", "").strip()


def request_json_with_cookies(url, timeout=10):
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar), urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://passport.bilibili.com/",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        headers = response.headers
    return payload, headers


def cookies_from_headers(headers):
    cookies = []
    for raw_header in headers.get_all("Set-Cookie") or []:
        pair = raw_header.split(";", 1)[0].strip()
        if pair and "=" in pair:
            cookies.append(pair)
    return "; ".join(cookies)


def qr_status_name(code):
    if code == 0:
        return "confirmed"
    if code == 86090:
        return "scanned"
    if code == 86101:
        return "waiting"
    if code == 86038:
        return "expired"
    return "error"
