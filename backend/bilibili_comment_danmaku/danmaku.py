import html
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone

from .scraper import (
    BLOCKED_API_CODES,
    BLOCKED_HTTP_STATUSES,
    DEFAULT_PROXY,
    GLOBAL_REQUEST_BACKOFF,
    BilibiliRequestError,
    log_backoff_wait,
    log_slow_request,
    retry_after_seconds,
    retry_delay_seconds,
)


def extract_cid(video_raw):
    if not video_raw:
        return None
    if video_raw.get("cid"):
        return video_raw.get("cid")
    pages = video_raw.get("pages") or []
    if pages and pages[0].get("cid"):
        return pages[0].get("cid")
    return None


def fetch_danmaku_xml(cid, headers=None, use_proxy=False, logger=None):
    log = logger or (lambda message: None)
    if use_proxy:
        os.environ.setdefault("HTTP_PROXY", DEFAULT_PROXY)
        os.environ.setdefault("HTTPS_PROXY", DEFAULT_PROXY)

    req = urllib.request.Request(
        f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}",
        headers=headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Referer": "https://www.bilibili.com",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({}))
    for attempt in range(1, 4):
        backoff_wait = GLOBAL_REQUEST_BACKOFF.wait()
        log_backoff_wait(log, req.full_url, backoff_wait, attempt, 3)
        started_at = time.perf_counter()
        try:
            with opener.open(req, timeout=30) as resp:
                body = decode_response_body(resp.read(), resp.headers.get("Content-Encoding"))
            log_slow_request(log, req.full_url, time.perf_counter() - started_at, attempt, 3, GLOBAL_REQUEST_BACKOFF)
            return body
        except urllib.error.HTTPError as exc:
            elapsed = time.perf_counter() - started_at
            if exc.code not in BLOCKED_HTTP_STATUSES:
                raise
            delay = max(retry_after_seconds(exc) or 0, retry_delay_seconds(attempt, status=exc.code))
            if attempt == 3:
                raise BilibiliRequestError(
                    f"HTTP Error {exc.code}: danmaku XML request blocked",
                    status=exc.code,
                    cause=exc,
                    retry_after=retry_after_seconds(exc),
                ) from exc
            GLOBAL_REQUEST_BACKOFF.block_for(delay)
            log(
                f"danmaku: XML got HTTP {exc.code}; elapsed={elapsed:.1f}s "
                f"cooling down for {delay:.0f}s before retry"
            )
            time.sleep(delay)
    raise BilibiliRequestError(f"danmaku XML request failed cid={cid}")


def decode_response_body(body, content_encoding):
    encoding = (content_encoding or "").lower()
    if "gzip" in encoding:
        return gzip.decompress(body)
    if "deflate" in encoding:
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def parse_danmaku_xml(xml_bytes, bvid, cid):
    root = ET.fromstring(xml_bytes)
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for node in root.findall("d"):
        attrs = (node.attrib.get("p") or "").split(",")
        if len(attrs) < 8:
            continue
        rows.append(
            {
                "bvid": bvid,
                "cid": str(cid),
                "dmid": attrs[7],
                "progress": parse_float(attrs[0], 0.0),
                "mode": parse_int(attrs[1], 0),
                "font_size": parse_int(attrs[2], 0),
                "color": parse_int(attrs[3], 0),
                "ctime": parse_int(attrs[4], 0),
                "pool": parse_int(attrs[5], 0),
                "user_hash": attrs[6],
                "weight": parse_int(attrs[8], None) if len(attrs) > 8 else None,
                "content": html.unescape(node.text or ""),
                "fetched_at": fetched_at,
                "like_count": 0,
            }
        )
    return rows


def fetch_danmaku_like_counts(cid, dmids, headers=None, use_proxy=False, logger=None):
    if not dmids:
        return {}
    log = logger or (lambda message: None)
    if use_proxy:
        os.environ.setdefault("HTTP_PROXY", DEFAULT_PROXY)
        os.environ.setdefault("HTTPS_PROXY", DEFAULT_PROXY)

    counts = {}
    for index in range(0, len(dmids), 100):
        chunk = dmids[index : index + 100]
        log(f"danmaku likes: batch {index // 100 + 1} ids={len(chunk)}")
        query = urllib.parse.urlencode({"oid": cid, "ids": ",".join(chunk)})
        req = urllib.request.Request(
            f"https://api.bilibili.com/x/v2/dm/thumbup/stats?{query}",
            headers=headers or {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
                "Referer": "https://www.bilibili.com",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({}))
        payload = None
        for attempt in range(1, 4):
            backoff_wait = GLOBAL_REQUEST_BACKOFF.wait()
            log_backoff_wait(log, req.full_url, backoff_wait, attempt, 3)
            started_at = time.perf_counter()
            try:
                with opener.open(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                log_slow_request(
                    log,
                    req.full_url,
                    time.perf_counter() - started_at,
                    attempt,
                    3,
                    GLOBAL_REQUEST_BACKOFF,
                )
            except urllib.error.HTTPError as exc:
                elapsed = time.perf_counter() - started_at
                if exc.code not in BLOCKED_HTTP_STATUSES:
                    raise
                delay = max(retry_after_seconds(exc) or 0, retry_delay_seconds(attempt, status=exc.code))
                if attempt == 3:
                    raise BilibiliRequestError(
                        f"HTTP Error {exc.code}: danmaku like request blocked",
                        status=exc.code,
                        cause=exc,
                        retry_after=retry_after_seconds(exc),
                    ) from exc
                GLOBAL_REQUEST_BACKOFF.block_for(delay)
                log(
                    f"danmaku likes: got HTTP {exc.code}; elapsed={elapsed:.1f}s "
                    f"cooling down for {delay:.0f}s before retry"
                )
                time.sleep(delay)
                continue

            api_code = payload.get("code")
            if api_code not in BLOCKED_API_CODES:
                break
            delay = retry_delay_seconds(attempt, api_code=api_code)
            if attempt == 3:
                raise BilibiliRequestError(
                    f"API code={api_code} message={payload.get('message')}",
                    api_code=api_code,
                )
            GLOBAL_REQUEST_BACKOFF.block_for(delay)
            log(f"danmaku likes: got API code {api_code}; cooling down for {delay:.0f}s before retry")
            time.sleep(delay)

        if payload is None:
            continue
        api_code = payload.get("code")
        if api_code != 0:
            continue
        data = payload.get("data") or {}
        for dmid, value in data.items():
            if isinstance(value, dict):
                counts[str(dmid)] = parse_int(value.get("likes") or value.get("like"), 0)
            else:
                counts[str(dmid)] = parse_int(value, 0)
        time.sleep(0.05)
    return counts


def scrape_danmaku(bvid, video_raw, headers=None, use_proxy=False, logger=None):
    log = logger or (lambda message: None)
    cid = extract_cid(video_raw)
    if not cid:
        log("danmaku: skipped because video cid is missing")
        return {"bvid": bvid, "cid": None, "items": []}
    log(f"danmaku: fetching xml cid={cid}")
    xml_bytes = fetch_danmaku_xml(cid, headers=headers, use_proxy=use_proxy, logger=log)
    items = parse_danmaku_xml(xml_bytes, bvid, cid)
    log(f"danmaku: parsed xml items={len(items)}")
    try:
        like_counts = fetch_danmaku_like_counts(
            cid,
            [item["dmid"] for item in items],
            headers=headers,
            use_proxy=use_proxy,
            logger=log,
        )
    except Exception as exc:
        like_counts = {}
        log(f"danmaku likes: skipped because {exc}")
    for item in items:
        item["like_count"] = like_counts.get(item["dmid"], 0)
    log(f"danmaku: cid={cid} got={len(items)}")
    time.sleep(0.05)
    return {"bvid": bvid, "cid": str(cid), "items": items}


def parse_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
