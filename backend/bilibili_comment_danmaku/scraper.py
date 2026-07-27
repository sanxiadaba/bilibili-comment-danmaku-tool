import hashlib
import http.cookiejar
import copy
import json
import os
import queue
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import save_comments_to_sqlite
from .url_utils import extract_bvid
from .wbi import (
    MIXIN_KEY_ENC_TAB,
    WBI_BAD_CHARS,
    WBI_CACHE_PATH_ENV,
    WBI_MIXIN_KEY_CACHE,
    WBI_MIXIN_KEY_STALE_TTL_SECONDS,
    WBI_MIXIN_KEY_TTL_SECONDS,
    default_wbi_cache_path,
    filename_stem,
    get_cached_wbi_mixin_key,
    get_mixin_key,
    load_persisted_wbi_mixin_key,
    persist_wbi_mixin_key,
    remember_wbi_mixin_key,
    sign_wbi_params,
)


DEFAULT_BVID = "BV1LrVS6vE1D"
DEFAULT_PROXY = "http://127.0.0.1:7890"
TYPE_VIDEO = 1
FAST_PAGE_YIELD_SECONDS = 0.02
FULL_DELAY_EVERY_PAGES = 20
CHILD_PAGE_YIELD_SECONDS = 0.12
CHILD_FULL_DELAY_EVERY_PAGES = 10
MAX_CHILD_FETCH_WORKERS = 4
BLOCKED_HTTP_STATUSES = {412, 429}
BLOCKED_API_CODES = {-352}
SESSION_RETRY_HTTP_STATUSES = {412}
RATE_LIMIT_HTTP_STATUSES = {429}
SESSION_RETRY_DELAYS = (12, 45, 120)
SESSION_RETRY_JITTER_SECONDS = (2, 8)
RATE_LIMIT_RETRY_DELAYS = (180, 600, 1800)
RATE_LIMIT_RETRY_JITTER_SECONDS = (15, 90)
GLOBAL_MIN_REQUEST_INTERVAL_SECONDS = 0.85
REQUEST_INTERVAL_JITTER_SECONDS = (0.05, 0.45)
CHILD_REQUEST_SPACING_FACTOR = 0.65
SLOW_REQUEST_WARN_SECONDS = 12
VERY_SLOW_REQUEST_SECONDS = 60
VERY_SLOW_REQUEST_COOLDOWN_SECONDS = (30, 90)
SLOW_LIMIT_MIN_ELAPSED_SECONDS = 90
SLOW_LIMIT_WINDOW_SECONDS = 900
SLOW_LIMIT_TRIGGER_COUNT = 3
SLOW_LIMIT_COOLDOWN_SECONDS = (900, 1800)
SLOW_LIMIT_RECOVERY_WINDOW_SECONDS = 3600
SLOW_LIMIT_MAX_LEVEL = 4
SLOW_LIMIT_MAX_COOLDOWN_SECONDS = 21600
SLOW_LIMIT_FAST_RECOVERY_COUNT = 8
SIGNED_REQUEST_RETRIES = 3
CHINA_TZ = timezone(timedelta(hours=8))
BROWSER_ID_COOKIE_NAMES = {"buvid3", "buvid4", "buvid_fp", "b_nut"}
WBI_NAV_HARD_TIMEOUT_SECONDS = 10
BACKOFF_STATE_PATH_ENV = "BILIBILI_BACKOFF_STATE_PATH"
BACKOFF_STATE_MAX_AGE_SECONDS = 24 * 60 * 60
COMMENTS_CLOSED_API_CODES = {12061}
ORIGINAL_GETADDRINFO = socket.getaddrinfo
IPV4_FIRST_DNS_INSTALLED = False
IPV4_FIRST_DNS_LOCK = threading.Lock()


class BilibiliRequestError(RuntimeError):
    def __init__(
        self,
        message,
        *,
        status=None,
        api_code=None,
        api_message=None,
        url=None,
        cause=None,
        retry_after=None,
    ):
        super().__init__(message)
        self.status = status
        self.api_code = api_code
        self.api_message = api_message
        self.url = url
        self.retry_after = retry_after
        self.__cause__ = cause


class WbiSignatureUnavailableError(RuntimeError):
    def __init__(self, message, *, cause=None):
        super().__init__(message)
        self.__cause__ = cause


def install_ipv4_first_dns():
    global IPV4_FIRST_DNS_INSTALLED
    if IPV4_FIRST_DNS_INSTALLED:
        return
    with IPV4_FIRST_DNS_LOCK:
        if IPV4_FIRST_DNS_INSTALLED:
            return

        def ipv4_first_getaddrinfo(*args, **kwargs):
            infos = ORIGINAL_GETADDRINFO(*args, **kwargs)
            return sorted(infos, key=lambda item: 0 if item[0] == socket.AF_INET else 1)

        socket.getaddrinfo = ipv4_first_getaddrinfo
        IPV4_FIRST_DNS_INSTALLED = True


def default_backoff_state_path():
    configured = os.environ.get(BACKOFF_STATE_PATH_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "bilibili_backoff_state.json"


class RequestBackoff:
    def __init__(
        self,
        min_interval=GLOBAL_MIN_REQUEST_INTERVAL_SECONDS,
        interval_jitter=REQUEST_INTERVAL_JITTER_SECONDS,
        state_path=None,
        persist=True,
    ):
        self.lock = threading.Lock()
        self.blocked_until = 0
        self.next_request_at = 0
        self.slow_request_times = []
        self.slow_limit_level = 0
        self.last_slow_limit_at = 0
        self.fast_request_count = 0
        self.min_interval = min_interval
        self.interval_jitter = interval_jitter
        self.state_path = Path(state_path) if state_path else default_backoff_state_path()
        self.persist = persist
        self.load_state()

    def wait(self, include_spacing=True, spacing_factor=1.0, cancel_check=None):
        total_sleep = 0
        try:
            spacing_factor = max(float(spacing_factor), 0)
        except (TypeError, ValueError):
            spacing_factor = 1.0
        while True:
            with self.lock:
                now = time.monotonic()
                spacing_until = self.next_request_at if include_spacing else 0
                sleep_for = max(self.blocked_until - now, spacing_until - now)
                if sleep_for <= 0:
                    if include_spacing:
                        spacing = (
                            self.min_interval * spacing_factor
                            + random.uniform(*self.interval_jitter) * spacing_factor
                        )
                        self.next_request_at = now + max(spacing, 0)
                    return total_sleep
            total_sleep += sleep_for
            interruptible_sleep(sleep_for, cancel_check)

    def block_for(self, seconds):
        if seconds <= 0:
            return
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)
            self.save_state_locked()

    def note_slow_request(
        self,
        elapsed,
        *,
        threshold=SLOW_LIMIT_MIN_ELAPSED_SECONDS,
        window=SLOW_LIMIT_WINDOW_SECONDS,
        trigger_count=SLOW_LIMIT_TRIGGER_COUNT,
    ):
        if elapsed < threshold:
            return 0

        with self.lock:
            now = time.monotonic()
            self.fast_request_count = 0
            cutoff = now - window
            self.slow_request_times = [event_at for event_at in self.slow_request_times if event_at >= cutoff]
            self.slow_request_times.append(now)
            in_recovery_window = (
                self.last_slow_limit_at > 0
                and now - self.last_slow_limit_at <= SLOW_LIMIT_RECOVERY_WINDOW_SECONDS
            )
            if len(self.slow_request_times) < trigger_count and not in_recovery_window:
                return 0

            self.slow_limit_level = min(self.slow_limit_level + 1, SLOW_LIMIT_MAX_LEVEL)
            multiplier = 2 ** max(self.slow_limit_level - 1, 0)
            cooldown_min = min(SLOW_LIMIT_COOLDOWN_SECONDS[0] * multiplier, SLOW_LIMIT_MAX_COOLDOWN_SECONDS)
            cooldown_max = min(SLOW_LIMIT_COOLDOWN_SECONDS[1] * multiplier, SLOW_LIMIT_MAX_COOLDOWN_SECONDS)
            cooldown = random.uniform(cooldown_min, max(cooldown_min, cooldown_max))
            self.blocked_until = max(self.blocked_until, now + cooldown)
            self.last_slow_limit_at = now
            self.slow_request_times.clear()
            self.save_state_locked()
            return cooldown

    def note_fast_request(
        self,
        elapsed,
        *,
        threshold=SLOW_LIMIT_MIN_ELAPSED_SECONDS,
        recovery_count=SLOW_LIMIT_FAST_RECOVERY_COUNT,
    ):
        if elapsed >= threshold:
            return

        with self.lock:
            if self.slow_limit_level <= 0:
                return
            self.fast_request_count += 1
            if self.fast_request_count >= recovery_count:
                self.slow_limit_level -= 1
                self.fast_request_count = 0
                self.save_state_locked()

    def load_state(self):
        if not self.persist:
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        wall_now = time.time()
        monotonic_now = time.monotonic()
        try:
            updated_at = float(payload.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0
        if updated_at and wall_now - updated_at > BACKOFF_STATE_MAX_AGE_SECONDS:
            return

        def epoch_to_monotonic(value):
            try:
                epoch_value = float(value)
            except (TypeError, ValueError):
                return None
            return monotonic_now + (epoch_value - wall_now)

        blocked_until = epoch_to_monotonic(payload.get("blocked_until"))
        if blocked_until and blocked_until > monotonic_now:
            self.blocked_until = blocked_until

        cutoff_epoch = wall_now - SLOW_LIMIT_WINDOW_SECONDS
        slow_times = []
        for event_at in payload.get("slow_request_times") or []:
            try:
                event_epoch = float(event_at)
            except (TypeError, ValueError):
                continue
            if event_epoch >= cutoff_epoch:
                converted = epoch_to_monotonic(event_epoch)
                if converted is not None:
                    slow_times.append(converted)
        self.slow_request_times = slow_times

        try:
            self.slow_limit_level = min(max(int(payload.get("slow_limit_level") or 0), 0), SLOW_LIMIT_MAX_LEVEL)
        except (TypeError, ValueError):
            self.slow_limit_level = 0
        try:
            self.fast_request_count = max(int(payload.get("fast_request_count") or 0), 0)
        except (TypeError, ValueError):
            self.fast_request_count = 0
        last_slow_limit_at = epoch_to_monotonic(payload.get("last_slow_limit_at"))
        if last_slow_limit_at:
            self.last_slow_limit_at = last_slow_limit_at

    def save_state_locked(self):
        if not self.persist:
            return
        wall_now = time.time()
        monotonic_now = time.monotonic()

        def monotonic_to_epoch(value):
            if not value:
                return 0
            return wall_now + (value - monotonic_now)

        payload = {
            "updated_at": wall_now,
            "blocked_until": max(monotonic_to_epoch(self.blocked_until), 0),
            "slow_request_times": [
                monotonic_to_epoch(event_at)
                for event_at in self.slow_request_times
                if monotonic_to_epoch(event_at) > 0
            ],
            "slow_limit_level": self.slow_limit_level,
            "last_slow_limit_at": max(monotonic_to_epoch(self.last_slow_limit_at), 0),
            "fast_request_count": self.fast_request_count,
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_name(
                f"{self.state_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(self.state_path)
        except OSError:
            return


GLOBAL_REQUEST_BACKOFF = RequestBackoff()


def build_proxy_handler(use_proxy=False):
    configured_proxy = os.environ.get("BILIBILI_PROXY", "").strip()
    if configured_proxy:
        return urllib.request.ProxyHandler({"http": configured_proxy, "https": configured_proxy})
    return urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})


class BilibiliClient:
    def __init__(self, headers, use_proxy=False, backoff=None):
        install_ipv4_first_dns()
        self.headers = dict(headers)
        self.use_proxy = use_proxy
        self.backoff = backoff or GLOBAL_REQUEST_BACKOFF
        self.cookie_jar = http.cookiejar.CookieJar()
        cookie_header = self.headers.pop("Cookie", "")
        if cookie_header:
            seed_cookie_jar(self.cookie_jar, cookie_header)
        proxy_handler = build_proxy_handler(use_proxy)
        self.opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def clone(self):
        cloned = BilibiliClient(dict(self.headers), use_proxy=self.use_proxy, backoff=self.backoff)
        for cookie in self.cookie_jar:
            cloned.cookie_jar.set_cookie(copy.copy(cookie))
        return cloned

    def open_request(self, req, timeout):
        return self.opener.open(req, timeout=timeout)

    def request_json(
        self,
        url,
        timeout=30,
        retries=4,
        allow_api_error=False,
        logger=None,
        wait_for_backoff=True,
        wait_for_spacing=True,
        spacing_factor=1.0,
    ):
        log = logger or (lambda _message: None)
        cancel_check = logger_cancel_check(log)
        last_error = None
        for attempt in range(1, retries + 1):
            request_elapsed = 0
            try:
                if wait_for_backoff:
                    backoff_wait = self.backoff.wait(
                        include_spacing=wait_for_spacing,
                        spacing_factor=spacing_factor,
                        cancel_check=cancel_check,
                    )
                    log_backoff_wait(log, url, backoff_wait, attempt, retries)
                started_at = time.perf_counter()
                req = urllib.request.Request(url, headers=self.headers)
                with self.open_request(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                request_elapsed = time.perf_counter() - started_at
                log_slow_request(log, url, request_elapsed, attempt, retries, self.backoff)
                data = json.loads(body)
                if data.get("code") != 0 and not allow_api_error:
                    api_code = data.get("code")
                    api_message = data.get("message")
                    raise BilibiliRequestError(
                        f"API code={api_code} message={api_message}",
                        api_code=api_code,
                        api_message=api_message,
                        url=url,
                    )
                return data
            except urllib.error.HTTPError as exc:
                if request_elapsed == 0:
                    request_elapsed = time.perf_counter() - started_at
                last_error = exc
                retry_after = retry_after_seconds(exc)
                if exc.code in BLOCKED_HTTP_STATUSES:
                    delay = max(retry_after or 0, retry_delay_seconds(attempt, status=exc.code))
                else:
                    delay = retry_delay_seconds(attempt, status=exc.code)
                if attempt == retries:
                    break
                if exc.code in RATE_LIMIT_HTTP_STATUSES:
                    self.backoff.block_for(delay)
                    log(
                        f"warning: request got HTTP {exc.code}; "
                        f"endpoint={request_endpoint_label(url)} elapsed={request_elapsed:.1f}s "
                        f"cooling down for {delay:.0f}s before retry (attempt {attempt}/{retries})"
                    )
                interruptible_sleep(delay, cancel_check)
            except BilibiliRequestError as exc:
                if request_elapsed == 0:
                    request_elapsed = time.perf_counter() - started_at
                last_error = exc
                if is_blocked_request_error(exc):
                    delay = max(
                        exc.retry_after or 0,
                        retry_delay_seconds(attempt, status=exc.status, api_code=exc.api_code),
                    )
                else:
                    delay = retry_delay_seconds(attempt)
                if attempt == retries:
                    break
                if should_global_backoff(exc):
                    self.backoff.block_for(delay)
                    log(
                        f"warning: request got {blocked_error_label(exc)}; "
                        f"endpoint={request_endpoint_label(url)} elapsed={request_elapsed:.1f}s "
                        f"cooling down for {delay:.0f}s before retry (attempt {attempt}/{retries})"
                    )
                interruptible_sleep(delay, cancel_check)
            except Exception as exc:
                if request_elapsed == 0 and "started_at" in locals():
                    request_elapsed = time.perf_counter() - started_at
                last_error = exc
                if attempt == retries:
                    break
                delay = retry_delay_seconds(attempt)
                log(
                    f"warning: request failed endpoint={request_endpoint_label(url)} "
                    f"elapsed={request_elapsed:.1f}s retrying in {delay:.0f}s "
                    f"(attempt {attempt}/{retries}) error={type(exc).__name__}"
                )
                interruptible_sleep(delay, cancel_check)

        status = getattr(last_error, "code", None)
        if status:
            raise BilibiliRequestError(
                f"HTTP Error {status}: Request failed after {retries} attempts: {url}\n{last_error}",
                status=status,
                url=url,
                cause=last_error,
                retry_after=retry_after_seconds(last_error),
            )
        if isinstance(last_error, BilibiliRequestError):
            raise last_error
        raise BilibiliRequestError(
            f"Request failed after {retries} attempts: {url}\n{last_error}",
            url=url,
            cause=last_error,
        )

    def warmup(self, bvid, logger=None):
        log = logger or (lambda _message: None)
        req = urllib.request.Request(f"https://www.bilibili.com/video/{bvid}", headers=self.headers)
        for attempt in range(1, 4):
            backoff_wait = self.backoff.wait(cancel_check=logger_cancel_check(log))
            log_backoff_wait(log, req.full_url, backoff_wait, attempt, 3)
            try:
                log(f"warmup: fetching video page attempt={attempt}/3")
                with self.open_request(req, timeout=8) as resp:
                    resp.read(1024)
                return
            except urllib.error.HTTPError as exc:
                if exc.code not in BLOCKED_HTTP_STATUSES or attempt == 3:
                    raise
                delay = max(retry_after_seconds(exc) or 0, retry_delay_seconds(attempt, status=exc.code))
                self.backoff.block_for(delay)
                log(f"warning: warmup got HTTP {exc.code}; cooling down for {delay:.0f}s before retry")
                interruptible_sleep(delay, logger_cancel_check(log))
            except Exception as exc:
                log(f"warning: warmup skipped after {type(exc).__name__}: {exc}")
                return


def load_cookie_file(path):
    if not path or not Path(path).exists():
        return ""
    text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return ""

    cookies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) >= 7 and "bilibili.com" in columns[0]:
            cookies.append(f"{columns[5]}={columns[6]}")

    if cookies:
        return "; ".join(cookies)
    return text.replace("\r", "").replace("\n", "; ")


def inspect_cookie_status(path, *, check_remote=True):
    cookie_path = Path(path)
    status = {
        "exists": cookie_path.exists(),
        "path": str(cookie_path),
        "length": 0,
        "status": "missing",
        "message": "未找到 cookie 文件",
        "has_sessdata": False,
        "has_bili_jct": False,
        "has_dede_user_id": False,
        "has_browser_id": False,
        "bili_ticket_expires_at": "",
        "bili_ticket_expired": False,
        "nav_checked": False,
        "nav_code": None,
        "nav_message": "",
        "is_login": False,
        "mid_present": False,
        "uname_present": False,
        "wbi_present": False,
    }
    if not cookie_path.exists():
        return status

    cookie = load_cookie_file(cookie_path)
    status["length"] = len(cookie)
    if not cookie:
        status.update(status="empty", message="cookie 文件为空")
        return status

    values = parse_cookie_header(cookie)
    status.update(
        status="unchecked",
        message="cookie 文件已读取，尚未验证登录态",
        has_sessdata=bool(values.get("SESSDATA")),
        has_bili_jct=bool(values.get("bili_jct")),
        has_dede_user_id=bool(values.get("DedeUserID")),
        has_browser_id=bool(set(values) & BROWSER_ID_COOKIE_NAMES),
    )
    ticket_expires_at, ticket_expired = cookie_expiry_info(values.get("bili_ticket_expires"))
    status["bili_ticket_expires_at"] = ticket_expires_at
    status["bili_ticket_expired"] = ticket_expired

    if not check_remote:
        return status

    try:
        client = BilibiliClient(make_headers(DEFAULT_BVID, cookie), use_proxy=False)
        nav = client.request_json(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=8,
            retries=1,
            allow_api_error=True,
            wait_for_backoff=False,
        )
        data = nav.get("data") or {}
        wbi_img = data.get("wbi_img") or {}
        is_login = bool(data.get("isLogin"))
        status.update(
            nav_checked=True,
            nav_code=nav.get("code"),
            nav_message=nav.get("message") or "",
            is_login=is_login,
            mid_present=bool(data.get("mid")),
            uname_present=bool(data.get("uname")),
            wbi_present=bool(wbi_img.get("img_url") and wbi_img.get("sub_url")),
            status="valid" if is_login else "invalid",
            message="Bilibili 已识别登录态" if is_login else "Bilibili 返回账号未登录，请更新 data/cookie.txt",
        )
    except Exception as exc:
        status.update(
            status="error",
            message=f"cookie 登录态验证失败：{type(exc).__name__}",
            nav_message=str(exc),
        )
    return status


def parse_cookie_header(cookie_header):
    values = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name:
            values[name.strip()] = value.strip()
    return values


def cookie_expiry_info(raw_value):
    if not raw_value:
        return "", False
    try:
        expires_at = datetime.fromtimestamp(int(raw_value), timezone.utc)
    except (TypeError, ValueError, OSError):
        return "", False
    return expires_at.isoformat(), expires_at <= datetime.now(timezone.utc)


def make_headers(bvid, cookie=""):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "Origin": "https://www.bilibili.com",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def seed_cookie_jar(cookie_jar, cookie_header):
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        if not name:
            continue
        cookie_jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=name.strip(),
                value=value.strip(),
                port=None,
                port_specified=False,
                domain=".bilibili.com",
                domain_specified=True,
                domain_initial_dot=True,
                path="/",
                path_specified=True,
                secure=False,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )


def cookie_has_browser_identifiers(cookie_header):
    names = set()
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _value = part.split("=", 1)
        names.add(name.strip())
    return bool(names & BROWSER_ID_COOKIE_NAMES)


def build_url(endpoint, params):
    return endpoint + "?" + urllib.parse.urlencode(params)


def call_with_hard_timeout(func, timeout_seconds, timeout_message):
    results = queue.Queue(maxsize=1)

    def target():
        try:
            results.put(("ok", func()))
        except Exception as exc:
            results.put(("error", exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        kind, value = results.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError(timeout_message) from exc
    if kind == "error":
        raise value
    return value


def fetch_wbi_nav_with_system_opener(headers, timeout=8):
    nav_headers = {
        key: value
        for key, value in dict(headers or {}).items()
        if key.lower() != "cookie"
    }
    nav_headers["Connection"] = "close"
    req = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=nav_headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset, errors="replace"))


def retry_delay_seconds(attempt, status=None, api_code=None):
    if status in SESSION_RETRY_HTTP_STATUSES:
        index = min(max(attempt, 1), len(SESSION_RETRY_DELAYS)) - 1
        base_delay = SESSION_RETRY_DELAYS[index]
        jitter = random.uniform(*SESSION_RETRY_JITTER_SECONDS)
        return base_delay + jitter
    if status in RATE_LIMIT_HTTP_STATUSES or api_code in BLOCKED_API_CODES:
        index = min(max(attempt, 1), len(RATE_LIMIT_RETRY_DELAYS)) - 1
        base_delay = RATE_LIMIT_RETRY_DELAYS[index]
        jitter = random.uniform(*RATE_LIMIT_RETRY_JITTER_SECONDS)
        return base_delay + jitter
    return min(2 * attempt, 8)


def logger_cancel_check(logger):
    return getattr(logger, "check_cancel", None)


def interruptible_sleep(seconds, cancel_check=None, quantum=0.5):
    seconds = max(float(seconds or 0), 0)
    if cancel_check is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        cancel_check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, quantum))


def retry_after_seconds(error):
    headers = getattr(error, "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def request_endpoint_label(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return parsed.netloc or "unknown"
    return path


def log_slow_request(log, url, elapsed, attempt, retries, backoff):
    note_fast_request = getattr(backoff, "note_fast_request", None)
    if note_fast_request is not None:
        note_fast_request(elapsed)
    if elapsed < SLOW_REQUEST_WARN_SECONDS:
        return
    cooldown = 0
    slow_limit_cooldown = 0
    slow_limit_level = 0
    if elapsed >= VERY_SLOW_REQUEST_SECONDS:
        cooldown = random.uniform(*VERY_SLOW_REQUEST_COOLDOWN_SECONDS)
        backoff.block_for(cooldown)
        note_slow_request = getattr(backoff, "note_slow_request", None)
        if note_slow_request is not None:
            slow_limit_cooldown = note_slow_request(elapsed)
            slow_limit_level = getattr(backoff, "slow_limit_level", 0)
    message = (
        f"warning: slow request endpoint={request_endpoint_label(url)} "
        f"elapsed={elapsed:.1f}s attempt={attempt}/{retries}"
    )
    if cooldown:
        message += f" adaptive_cooldown={cooldown:.0f}s"
    if slow_limit_cooldown:
        message += (
            f" slow_limit_cooldown={slow_limit_cooldown:.0f}s "
            f"slow_limit_level={slow_limit_level} "
            f"reason=consecutive_very_slow_requests"
        )
    log(message)


def log_backoff_wait(log, url, elapsed, attempt, retries):
    if elapsed < SLOW_REQUEST_WARN_SECONDS:
        return
    log(
        f"warning: backoff wait endpoint={request_endpoint_label(url)} "
        f"elapsed={elapsed:.1f}s attempt={attempt}/{retries}"
    )


def is_blocked_request_error(exc):
    return (
        isinstance(exc, BilibiliRequestError)
        and (exc.status in BLOCKED_HTTP_STATUSES or exc.api_code in BLOCKED_API_CODES)
    )


def is_session_precondition_error(exc):
    return isinstance(exc, BilibiliRequestError) and exc.status in SESSION_RETRY_HTTP_STATUSES


def should_global_backoff(exc):
    return is_blocked_request_error(exc) and not is_session_precondition_error(exc)


def is_comments_closed_error(exc):
    return (
        isinstance(exc, BilibiliRequestError)
        and exc.api_code in COMMENTS_CLOSED_API_CODES
    )


def blocked_error_label(exc):
    if exc.status in BLOCKED_HTTP_STATUSES:
        return f"HTTP {exc.status}"
    return f"API code {exc.api_code}"


def request_signed_json(endpoint, params_factory, client, mixin_key, log, refresh_mixin_key=None):
    last_error = None
    for attempt in range(1, SIGNED_REQUEST_RETRIES + 1):
        params = sign_wbi_params(params_factory(), mixin_key)
        try:
            return client.request_json(build_url(endpoint, params), retries=1, logger=log)
        except BilibiliRequestError as exc:
            last_error = exc
            if not is_blocked_request_error(exc) or attempt == SIGNED_REQUEST_RETRIES:
                raise
            delay = max(
                exc.retry_after or 0,
                retry_delay_seconds(attempt, status=exc.status, api_code=exc.api_code),
            )
            backoff = getattr(client, "backoff", None)
            if backoff is not None and should_global_backoff(exc):
                backoff.block_for(delay)
            log(
                f"warning: signed request got {blocked_error_label(exc)}; "
                f"cooling down for {delay:.0f}s before retry (attempt {attempt}/{SIGNED_REQUEST_RETRIES})"
            )
            interruptible_sleep(delay, logger_cancel_check(log))
            if refresh_mixin_key is not None:
                try:
                    mixin_key = refresh_mixin_key()
                    log("refreshed WBI signature key after cooldown")
                except Exception as refresh_error:
                    log(f"warning: failed to refresh WBI signature key: {refresh_error}")
    raise last_error


def get_wbi_mixin_key(client, log, force_refresh=False):
    if not force_refresh:
        cached = get_cached_wbi_mixin_key()
        if cached:
            log("wbi: reused cached signature key")
            return cached

    try:
        nav = call_with_hard_timeout(
            lambda: client.request_json(
                "https://api.bilibili.com/x/web-interface/nav",
                timeout=8,
                retries=2,
                allow_api_error=True,
                logger=log,
                wait_for_backoff=False,
            ),
            WBI_NAV_HARD_TIMEOUT_SECONDS,
            "nav API timed out while fetching WBI signature key",
        )
    except Exception as exc:
        try:
            log("warning: direct nav API unavailable; trying system opener fallback without Cookie")
            nav = call_with_hard_timeout(
                lambda: fetch_wbi_nav_with_system_opener(client.headers, timeout=8),
                WBI_NAV_HARD_TIMEOUT_SECONDS,
                "system opener nav API timed out while fetching WBI signature key",
            )
            log("wbi: fetched signature key with system opener fallback")
        except Exception as fallback_exc:
            stale = load_persisted_wbi_mixin_key()
            if stale:
                remember_wbi_mixin_key(stale)
                log(
                    "warning: nav API unavailable; reused persisted WBI signature key "
                    f"({type(fallback_exc).__name__})"
                )
                return stale
            raise WbiSignatureUnavailableError(
                "WBI signature key is temporarily unavailable; nav API did not respond and no persisted key is available",
                cause=fallback_exc,
            ) from fallback_exc

    nav_code = nav.get("code")
    if nav_code in BLOCKED_API_CODES:
        delay = retry_delay_seconds(1, api_code=nav_code)
        client.backoff.block_for(delay)
        raise BilibiliRequestError(
            f"API code={nav_code} message={nav.get('message')}",
            api_code=nav_code,
        )
    data = nav.get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = wbi_img.get("img_url")
    sub_url = wbi_img.get("sub_url")
    if not img_url or not sub_url:
        raise RuntimeError(f"Could not get WBI image keys from nav API: code={nav_code} message={nav.get('message')}")

    log(f"login: isLogin={data.get('isLogin')} nav_code={nav_code}")
    mixin_key = get_mixin_key(filename_stem(img_url), filename_stem(sub_url))
    remember_wbi_mixin_key(mixin_key)
    return mixin_key


def unix_to_iso(value, tz):
    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, tz=tz).isoformat()


def normalize_reply(reply, level):
    member = reply.get("member") or {}
    content = reply.get("content") or {}
    control = reply.get("reply_control") or {}
    return {
        "level": level,
        "rpid": reply.get("rpid_str") or str(reply.get("rpid")),
        "oid": reply.get("oid_str") or str(reply.get("oid")),
        "type": reply.get("type"),
        "mid": reply.get("mid_str") or str(reply.get("mid")),
        "root": reply.get("root_str") or str(reply.get("root")),
        "parent": reply.get("parent_str") or str(reply.get("parent")),
        "dialog": reply.get("dialog_str") or str(reply.get("dialog")),
        "ctime": reply.get("ctime"),
        "time_iso": unix_to_iso(reply.get("ctime"), CHINA_TZ),
        "time_iso_utc": unix_to_iso(reply.get("ctime"), timezone.utc),
        "like": reply.get("like"),
        "rcount": reply.get("rcount"),
        "count": reply.get("count"),
        "state": reply.get("state"),
        "attr": reply.get("attr"),
        "message": content.get("message"),
        "emote": content.get("emote"),
        "pictures": content.get("pictures"),
        "jump_url": content.get("jump_url"),
        "ip_location": control.get("location"),
        "user": {
            "mid": member.get("mid"),
            "uname": member.get("uname"),
            "sex": member.get("sex"),
            "sign": member.get("sign"),
            "avatar": member.get("avatar"),
            "level": (member.get("level_info") or {}).get("current_level"),
            "vip": member.get("vip"),
            "official_verify": member.get("official_verify"),
            "pendant": member.get("pendant"),
            "nameplate": member.get("nameplate"),
        },
    }


def sort_key(item):
    ctime = item.get("normalized", {}).get("ctime")
    rpid = item.get("normalized", {}).get("rpid") or ""
    return (ctime if isinstance(ctime, int) else -1, str(rpid))


def fetch_video_info(bvid, client, log=None):
    url = build_url("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
    return client.request_json(url, logger=log)["data"]


def fetch_main_replies(oid, client, mixin_key, delay, log, max_pages=None):
    endpoint = "https://api.bilibili.com/x/v2/reply/wbi/main"
    replies = []
    seen_rpids = set()
    seen_cursors = set()
    next_cursor = 0
    page_index = 0
    api_comment_count = None

    while True:
        page_index += 1
        def make_params():
            return {
                "oid": oid,
                "type": TYPE_VIDEO,
                "mode": 2,
                "next": next_cursor,
                "ps": 20,
                "plat": 1,
                "web_location": 1315875,
            }

        try:
            data = request_signed_json(
                endpoint,
                make_params,
                client,
                mixin_key,
                log,
                refresh_mixin_key=lambda: get_wbi_mixin_key(client, log, force_refresh=True),
            )["data"]
        except BilibiliRequestError as exc:
            if is_comments_closed_error(exc):
                log(f"comments closed: oid={oid} api_code={exc.api_code}; using empty comment archive")
                return [], 0
            raise
        page_replies = collect_main_reply_candidates(data)
        cursor = data.get("cursor") or {}
        api_comment_count = cursor.get("all_count", api_comment_count)

        for reply in page_replies:
            rpid = reply.get("rpid_str") or str(reply.get("rpid"))
            if rpid not in seen_rpids:
                seen_rpids.add(rpid)
                replies.append(reply)

        log(
            f"main page {page_index}: got={len(page_replies)} unique={len(replies)} "
            f"all_count={api_comment_count} next={cursor.get('next')} is_end={cursor.get('is_end')}"
        )

        if isinstance(max_pages, int) and max_pages > 0 and page_index >= max_pages:
            log(f"main page limit reached: max_pages={max_pages} unique={len(replies)}")
            break
        if cursor.get("is_end"):
            break
        next_value = cursor.get("next")
        if next_value is None or next_value in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        next_cursor = next_value
        sleep_between_pages(delay, page_index)

    return replies, api_comment_count


def collect_main_reply_candidates(data):
    candidates = []
    for key in ("top_replies", "replies", "hots"):
        for reply in data.get(key) or []:
            if reply:
                candidates.append(reply)

    top = data.get("top") or {}
    for key in ("admin", "upper", "vote"):
        reply = top.get(key)
        if reply:
            candidates.append(reply)
    return candidates


def fetch_child_replies(oid, root_rpid, expected_count, client, delay, log):
    endpoint = "https://api.bilibili.com/x/v2/reply/reply"
    replies = []
    seen_rpids = set()
    page = 1
    api_count = None

    while True:
        params = {
            "type": TYPE_VIDEO,
            "oid": oid,
            "root": root_rpid,
            "pn": page,
            "ps": 20,
        }
        try:
            data = client.request_json(
                build_url(endpoint, params),
                logger=log,
                retries=1,
                spacing_factor=CHILD_REQUEST_SPACING_FACTOR,
            )["data"]
        except BilibiliRequestError as exc:
            if is_blocked_request_error(exc):
                delay = max(
                    exc.retry_after or 0,
                    retry_delay_seconds(1, status=exc.status, api_code=exc.api_code),
                )
                if should_global_backoff(exc):
                    client.backoff.block_for(delay)
                    log(
                        f"child root={root_rpid} blocked by {blocked_error_label(exc)}; "
                        f"cooling down for {delay:.0f}s and pausing current archive task"
                    )
                else:
                    log(
                        f"child root={root_rpid} got {blocked_error_label(exc)}; "
                        "login/session precondition failed, pausing current archive task without global cooldown"
                    )
            raise
        page_replies = collect_main_reply_candidates(data)
        page_info = data.get("page") or {}
        api_count = page_info.get("count", api_count)

        for reply in page_replies:
            rpid = reply.get("rpid_str") or str(reply.get("rpid"))
            if rpid not in seen_rpids:
                seen_rpids.add(rpid)
                replies.append(reply)

        log(
            f"  child root={root_rpid} page={page}: got={len(page_replies)} "
            f"unique={len(replies)} expected={expected_count} count={api_count}"
        )

        if not page_replies:
            break
        if isinstance(api_count, int) and len(replies) >= api_count:
            break
        if isinstance(expected_count, int) and expected_count > 0 and len(replies) >= expected_count:
            break
        page += 1
        sleep_between_child_pages(delay, page - 1)

    return replies, api_count


def build_threaded_output(main_replies, oid, client, delay, log, fetch_children=True):
    entries = []
    fetch_jobs = []
    expected_child_total = 0

    for index, reply in enumerate(main_replies, 1):
        root_rpid = reply.get("rpid_str") or str(reply.get("rpid"))
        expected_count = reply.get("rcount")
        child_raw = []
        child_seen = set()

        for child in reply.get("replies") or []:
            child_rpid = child.get("rpid_str") or str(child.get("rpid"))
            if child_rpid not in child_seen:
                child_seen.add(child_rpid)
                child_raw.append(child)

        entry = {
            "index": index,
            "reply": reply,
            "root_rpid": root_rpid,
            "expected_count": expected_count,
            "child_raw": child_raw,
            "child_api_count": None,
        }
        entries.append(entry)

        if isinstance(expected_count, int) and expected_count > len(child_raw):
            expected_child_total += expected_count
            fetch_jobs.append(entry)

    if fetch_children:
        fetch_children_for_entries(fetch_jobs, oid, client, delay, log, expected_child_total)
    elif fetch_jobs:
        log(
            f"skipping children fetch: roots={len(fetch_jobs)} "
            f"embedded_fetched={sum(len(entry['child_raw']) for entry in fetch_jobs)} "
            f"total_expected={expected_child_total}"
        )

    comments = []
    comment_items = []
    child_fetch_summary = []

    for entry in entries:
        reply = entry["reply"]
        expected_count = entry["expected_count"]
        child_raw = entry["child_raw"]
        child_api_count = entry["child_api_count"]

        child_items = [{"normalized": normalize_reply(child, level=2), "raw": child} for child in child_raw]
        child_items.sort(key=sort_key)

        item = {
            "normalized": normalize_reply(reply, level=1),
            "replies": child_items,
            "raw": reply,
        }
        comments.append(item)
        comment_items.append({"normalized": item["normalized"], "raw": reply})
        comment_items.extend(child_items)

        if isinstance(expected_count, int) and expected_count > 0:
            child_fetch_summary.append(
                {
                    "root_rpid": entry["root_rpid"],
                    "expected_rcount": expected_count,
                    "api_count": child_api_count,
                    "fetched_count": len(child_items),
                }
            )

    comments.sort(key=sort_key)
    comment_items.sort(key=sort_key)
    return comments, comment_items, child_fetch_summary


def fetch_children_for_entries(fetch_jobs, oid, client, delay, log, expected_child_total):
    if not fetch_jobs:
        return

    worker_count = min(MAX_CHILD_FETCH_WORKERS, len(fetch_jobs))
    completed = 0
    total_fetched = 0
    log(
        f"fetching children batch: roots={len(fetch_jobs)} workers={worker_count} "
        f"total_fetched=0 total_expected={expected_child_total}"
    )

    def run_job(entry):
        worker_client = client.clone()
        fetched_child_raw, child_api_count = fetch_child_replies(
            oid,
            entry["root_rpid"],
            entry["expected_count"],
            worker_client,
            delay,
            log,
        )
        return entry, fetched_child_raw, child_api_count

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(run_job, entry) for entry in fetch_jobs]
        for future in as_completed(futures):
            entry, fetched_child_raw, child_api_count = future.result()
            child_seen = {
                child.get("rpid_str") or str(child.get("rpid"))
                for child in entry["child_raw"]
            }
            for child in fetched_child_raw:
                child_rpid = child.get("rpid_str") or str(child.get("rpid"))
                if child_rpid not in child_seen:
                    child_seen.add(child_rpid)
                    entry["child_raw"].append(child)
            entry["child_api_count"] = child_api_count
            completed += 1
            total_fetched += len(entry["child_raw"])
            log(
                f"children done {completed}/{len(fetch_jobs)} root={entry['root_rpid']} "
                f"fetched={len(entry['child_raw'])} total_fetched={total_fetched} "
                f"total_expected={expected_child_total}"
            )

def sleep_between_pages(delay, page_index):
    if delay <= 0:
        return
    if page_index > 0 and page_index % FULL_DELAY_EVERY_PAGES == 0:
        time.sleep(delay)
        return
    time.sleep(min(delay, FAST_PAGE_YIELD_SECONDS))


def sleep_between_child_pages(delay, page_index):
    if delay <= 0:
        return
    if page_index > 0 and page_index % CHILD_FULL_DELAY_EVERY_PAGES == 0:
        time.sleep(delay)
        return
    time.sleep(min(delay, CHILD_PAGE_YIELD_SECONDS))


def scrape_comments(
    video_ref,
    cookie="",
    cookie_file="cookie.txt",
    delay=0.35,
    use_proxy=False,
    logger=None,
    max_main_pages=None,
    fetch_children=True,
):
    log = logger or (lambda message: print(message, flush=True))
    bvid = extract_bvid(video_ref)
    if use_proxy:
        os.environ.setdefault("HTTP_PROXY", DEFAULT_PROXY)
        os.environ.setdefault("HTTPS_PROXY", DEFAULT_PROXY)

    resolved_cookie = cookie
    if not resolved_cookie and cookie_file and Path(cookie_file).exists():
        resolved_cookie = load_cookie_file(cookie_file)
    if not resolved_cookie:
        log("warning: no cookie provided; Bilibili may only return a partial comment list")

    client = BilibiliClient(make_headers(bvid, resolved_cookie), use_proxy=use_proxy)
    if cookie_has_browser_identifiers(resolved_cookie):
        log("warmup: skipped because cookie already has browser identifiers")
    else:
        client.warmup(bvid, logger=log)
    log("wbi: fetching signature key")
    mixin_key = get_wbi_mixin_key(client, log)
    log(f"video info: fetching bvid={bvid}")
    video = fetch_video_info(bvid, client, log)
    oid = video["aid"]
    log(f"video: bvid={bvid} aid={oid} title={video.get('title')}")
    log(f"main replies: fetching first page oid={oid}")

    main_raw, api_comment_count = fetch_main_replies(
        oid,
        client,
        mixin_key,
        delay,
        log,
        max_pages=max_main_pages,
    )
    comments, comment_items, child_fetch_summary = build_threaded_output(
        main_raw,
        oid,
        client,
        delay,
        log,
        fetch_children=fetch_children,
    )
    expected_nested_comment_count = sum((reply.get("rcount") or 0) for reply in main_raw)
    fetched_nested_comment_count = max(len(comment_items) - len(comments), 0)

    return {
        "metadata": {
            "source_url": f"https://www.bilibili.com/video/{bvid}",
            "bvid": bvid,
            "aid": oid,
            "title": video.get("title"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sort": "ctime_ascending",
            "api_comment_count": api_comment_count,
            "top_level_comment_count": len(comments),
            "expected_nested_comment_count": expected_nested_comment_count,
            "nested_comment_count": fetched_nested_comment_count,
            "comment_total_count": len(comment_items),
            "is_partial_comment_archive": bool(
                (isinstance(max_main_pages, int) and max_main_pages > 0) or not fetch_children
            ),
            "max_main_pages": max_main_pages,
            "fetch_children": fetch_children,
            "child_fetch_summary": child_fetch_summary,
            "notes": [
                "comments contains top-level comments sorted by ctime ascending; each replies array is also sorted by ctime ascending",
                "comment_items contains all top-level and nested comments sorted globally by ctime ascending",
                "raw Bilibili reply objects, cookies, and request headers are not written to the database",
            ],
        },
        "video_raw": video,
        "comments": comments,
        "comment_items": comment_items,
    }


def scrape_comments_to_sqlite(
    video_ref,
    db_path="comment_danmaku.db",
    cookie="",
    cookie_file="cookie.txt",
    delay=0.35,
    use_proxy=False,
    logger=None,
    max_main_pages=None,
    fetch_children=True,
):
    output_data = scrape_comments(
        video_ref,
        cookie=cookie,
        cookie_file=cookie_file,
        delay=delay,
        use_proxy=use_proxy,
        logger=logger,
        max_main_pages=max_main_pages,
        fetch_children=fetch_children,
    )
    return save_comments_to_sqlite(output_data, db_path)
