import hashlib
import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import save_comments_to_sqlite
from .url_utils import extract_bvid


DEFAULT_BVID = "BV1LrVS6vE1D"
DEFAULT_PROXY = "http://127.0.0.1:7890"
TYPE_VIDEO = 1
FAST_PAGE_YIELD_SECONDS = 0.02
FULL_DELAY_EVERY_PAGES = 20
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


class BilibiliClient:
    def __init__(self, headers, use_proxy=False):
        self.headers = headers
        self.cookie_jar = http.cookiejar.CookieJar()
        proxy_handler = urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})
        self.opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def request_json(self, url, timeout=30, retries=4, allow_api_error=False):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with self.opener.open(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                data = json.loads(body)
                if data.get("code") != 0 and not allow_api_error:
                    raise RuntimeError(f"API code={data.get('code')} message={data.get('message')}")
                return data
            except Exception as exc:
                last_error = exc
                if attempt == retries:
                    break
                time.sleep(min(2 * attempt, 8))
        raise RuntimeError(f"Request failed after {retries} attempts: {url}\n{last_error}")

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
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "Origin": "https://www.bilibili.com",
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
        params = sign_wbi_params(
            {
                "oid": oid,
                "type": TYPE_VIDEO,
                "mode": 2,
                "next": next_cursor,
                "ps": 20,
                "plat": 1,
                "web_location": 1315875,
            },
            mixin_key,
        )
        data = client.request_json(build_url(endpoint, params))["data"]
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
        sleep_between_pages(delay, page - 1)

    return replies, api_count


def build_threaded_output(main_replies, oid, client, delay, log):
    comments = []
    comment_items = []
    child_fetch_summary = []

    for index, reply in enumerate(main_replies, 1):
        root_rpid = reply.get("rpid_str") or str(reply.get("rpid"))
        expected_count = reply.get("rcount")
        child_raw = []
        child_seen = set()
        child_api_count = None

        for child in reply.get("replies") or []:
            child_rpid = child.get("rpid_str") or str(child.get("rpid"))
            if child_rpid not in child_seen:
                child_seen.add(child_rpid)
                child_raw.append(child)

        if isinstance(expected_count, int) and expected_count > len(child_raw):
            log(f"fetching children {index}/{len(main_replies)} root={root_rpid} expected={expected_count}")
            fetched_child_raw, child_api_count = fetch_child_replies(oid, root_rpid, expected_count, client, delay, log)
            for child in fetched_child_raw:
                child_rpid = child.get("rpid_str") or str(child.get("rpid"))
                if child_rpid not in child_seen:
                    child_seen.add(child_rpid)
                    child_raw.append(child)
            sleep_between_roots(delay)

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
                    "root_rpid": root_rpid,
                    "expected_rcount": expected_count,
                    "api_count": child_api_count,
                    "fetched_count": len(child_items),
                }
            )

    comments.sort(key=sort_key)
    comment_items.sort(key=sort_key)
    return comments, comment_items, child_fetch_summary


def sleep_between_pages(delay, page_index):
    if delay <= 0:
        return
    if page_index > 0 and page_index % FULL_DELAY_EVERY_PAGES == 0:
        time.sleep(delay)
        return
    time.sleep(min(delay, FAST_PAGE_YIELD_SECONDS))


def sleep_between_roots(delay):
    if delay <= 0:
        return
    time.sleep(min(delay, FAST_PAGE_YIELD_SECONDS))


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

