import hashlib
import http.cookiejar
import copy
import json
import os
import random
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
BLOCKED_RETRY_DELAYS = (60, 180, 600)
BLOCKED_RETRY_JITTER_SECONDS = (3, 18)
SIGNED_REQUEST_RETRIES = 3
CHINA_TZ = timezone(timedelta(hours=8))
MIXIN_KEY_ENC_TAB = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]
WBI_BAD_CHARS = "!'()*"


class BilibiliRequestError(RuntimeError):
    def __init__(self, message, *, status=None, api_code=None, url=None, cause=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.api_code = api_code
        self.url = url
        self.retry_after = retry_after
        self.__cause__ = cause


class RequestBackoff:
    def __init__(self):
        self.lock = threading.Lock()
        self.blocked_until = 0

    def wait(self):
        with self.lock:
            sleep_for = self.blocked_until - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)

    def block_for(self, seconds):
        if seconds <= 0:
            return
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)


GLOBAL_REQUEST_BACKOFF = RequestBackoff()


class BilibiliClient:
    def __init__(self, headers, use_proxy=False, backoff=None):
        self.headers = headers
        self.use_proxy = use_proxy
        self.backoff = backoff or GLOBAL_REQUEST_BACKOFF
        self.cookie_jar = http.cookiejar.CookieJar()
        proxy_handler = urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})
        self.opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def clone(self):
        cloned = BilibiliClient(dict(self.headers), use_proxy=self.use_proxy, backoff=self.backoff)
        for cookie in self.cookie_jar:
            cloned.cookie_jar.set_cookie(copy.copy(cookie))
        return cloned

    def request_json(self, url, timeout=30, retries=4, allow_api_error=False):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                self.backoff.wait()
                req = urllib.request.Request(url, headers=self.headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                data = json.loads(body)
                if data.get("code") != 0 and not allow_api_error:
                    api_code = data.get("code")
                    if api_code in BLOCKED_API_CODES:
                        raise BilibiliRequestError(
                            f"API code={api_code} message={data.get('message')}",
                            api_code=api_code,
                            url=url,
                        )
                    raise RuntimeError(f"API code={data.get('code')} message={data.get('message')}")
                return data
            except urllib.error.HTTPError as exc:
                last_error = exc
                retry_after = retry_after_seconds(exc)
                if exc.code in BLOCKED_HTTP_STATUSES:
                    delay = max(retry_after or 0, retry_delay_seconds(attempt, status=exc.code))
                else:
                    delay = retry_delay_seconds(attempt, status=exc.code)
                if attempt == retries:
                    break
                if exc.code in BLOCKED_HTTP_STATUSES:
                    self.backoff.block_for(delay)
                time.sleep(delay)
            except BilibiliRequestError as exc:
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
                if is_blocked_request_error(exc):
                    self.backoff.block_for(delay)
                time.sleep(delay)
            except Exception as exc:
                last_error = exc
                if attempt == retries:
                    break
                time.sleep(retry_delay_seconds(attempt))

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

    def warmup(self, bvid):
        req = urllib.request.Request(f"https://www.bilibili.com/video/{bvid}", headers=self.headers)
        with self.opener.open(req, timeout=30) as resp:
            resp.read(1024)


def load_cookie_file(path):
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


def make_headers(bvid, cookie=""):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "Origin": "https://www.bilibili.com",
        "Connection": "keep-alive",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def build_url(endpoint, params):
    return endpoint + "?" + urllib.parse.urlencode(params)


def filename_stem(url):
    return Path(urllib.parse.urlparse(url).path).stem


def get_mixin_key(img_key, sub_key):
    raw = img_key + sub_key
    return "".join(raw[index] for index in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi_params(params, mixin_key):
    signed = dict(params)
    signed["wts"] = int(time.time())
    cleaned = {
        key: "".join(ch for ch in str(value) if ch not in WBI_BAD_CHARS)
        for key, value in signed.items()
    }
    query = urllib.parse.urlencode(sorted(cleaned.items()))
    cleaned["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return cleaned


def retry_delay_seconds(attempt, status=None, api_code=None):
    if status in BLOCKED_HTTP_STATUSES or api_code in BLOCKED_API_CODES:
        index = min(max(attempt, 1), len(BLOCKED_RETRY_DELAYS)) - 1
        base_delay = BLOCKED_RETRY_DELAYS[index]
        jitter = random.uniform(*BLOCKED_RETRY_JITTER_SECONDS)
        return base_delay + jitter
    return min(2 * attempt, 8)


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


def is_blocked_request_error(exc):
    return (
        isinstance(exc, BilibiliRequestError)
        and (exc.status in BLOCKED_HTTP_STATUSES or exc.api_code in BLOCKED_API_CODES)
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
            return client.request_json(build_url(endpoint, params), retries=1)
        except BilibiliRequestError as exc:
            last_error = exc
            if not is_blocked_request_error(exc) or attempt == SIGNED_REQUEST_RETRIES:
                raise
            delay = max(
                exc.retry_after or 0,
                retry_delay_seconds(attempt, status=exc.status, api_code=exc.api_code),
            )
            backoff = getattr(client, "backoff", None)
            if backoff is not None:
                backoff.block_for(delay)
            log(
                f"warning: signed request got {blocked_error_label(exc)}; "
                f"cooling down for {delay:.0f}s before retry (attempt {attempt}/{SIGNED_REQUEST_RETRIES})"
            )
            time.sleep(delay)
            if refresh_mixin_key is not None:
                try:
                    mixin_key = refresh_mixin_key()
                    log("refreshed WBI signature key after cooldown")
                except Exception as refresh_error:
                    log(f"warning: failed to refresh WBI signature key: {refresh_error}")
    raise last_error


def get_wbi_mixin_key(client, log):
    nav = client.request_json(
        "https://api.bilibili.com/x/web-interface/nav",
        timeout=30,
        allow_api_error=True,
    )
    data = nav.get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = wbi_img.get("img_url")
    sub_url = wbi_img.get("sub_url")
    if not img_url or not sub_url:
        raise RuntimeError(f"Could not get WBI image keys from nav API: code={nav.get('code')} message={nav.get('message')}")

    log(f"login: isLogin={data.get('isLogin')} nav_code={nav.get('code')}")
    return get_mixin_key(filename_stem(img_url), filename_stem(sub_url))


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


def fetch_video_info(bvid, client):
    url = build_url("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
    return client.request_json(url)["data"]


def fetch_main_replies(oid, client, mixin_key, delay, log):
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

        data = request_signed_json(
            endpoint,
            make_params,
            client,
            mixin_key,
            log,
            refresh_mixin_key=lambda: get_wbi_mixin_key(client, log),
        )["data"]
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
        data = client.request_json(build_url(endpoint, params))["data"]
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


def build_threaded_output(main_replies, oid, client, delay, log):
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

    fetch_children_for_entries(fetch_jobs, oid, client, delay, log, expected_child_total)

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


def scrape_comments(video_ref, cookie="", cookie_file="cookie.txt", delay=0.35, use_proxy=False, logger=None):
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
    client.warmup(bvid)
    mixin_key = get_wbi_mixin_key(client, log)
    video = fetch_video_info(bvid, client)
    oid = video["aid"]
    log(f"video: bvid={bvid} aid={oid} title={video.get('title')}")

    main_raw, api_comment_count = fetch_main_replies(oid, client, mixin_key, delay, log)
    comments, comment_items, child_fetch_summary = build_threaded_output(main_raw, oid, client, delay, log)
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


def scrape_comments_to_sqlite(video_ref, db_path="comment_danmaku.db", cookie="", cookie_file="cookie.txt", delay=0.35, use_proxy=False, logger=None):
    output_data = scrape_comments(
        video_ref,
        cookie=cookie,
        cookie_file=cookie_file,
        delay=delay,
        use_proxy=use_proxy,
        logger=logger,
    )
    return save_comments_to_sqlite(output_data, db_path)

