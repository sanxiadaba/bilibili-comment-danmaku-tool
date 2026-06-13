import hashlib
import json
import os
import threading
import time
import urllib.parse
from pathlib import Path


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
WBI_MIXIN_KEY_TTL_SECONDS = 1800
WBI_MIXIN_KEY_STALE_TTL_SECONDS = 24 * 60 * 60
WBI_CACHE_PATH_ENV = "BILIBILI_WBI_CACHE_PATH"
WBI_MIXIN_KEY_CACHE = {
    "value": None,
    "expires_at": 0,
}
WBI_MIXIN_KEY_CACHE_LOCK = threading.Lock()


def default_wbi_cache_path():
    configured = os.environ.get(WBI_CACHE_PATH_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "wbi_mixin_key.json"


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


def get_cached_wbi_mixin_key():
    now = time.time()
    with WBI_MIXIN_KEY_CACHE_LOCK:
        value = WBI_MIXIN_KEY_CACHE.get("value")
        expires_at = WBI_MIXIN_KEY_CACHE.get("expires_at") or 0
        if value and expires_at > now:
            return value
    cached = load_persisted_wbi_mixin_key(max_age_seconds=WBI_MIXIN_KEY_TTL_SECONDS)
    if cached:
        remember_wbi_mixin_key(cached)
        return cached
    return None


def remember_wbi_mixin_key(mixin_key):
    expires_at = time.time() + WBI_MIXIN_KEY_TTL_SECONDS
    with WBI_MIXIN_KEY_CACHE_LOCK:
        WBI_MIXIN_KEY_CACHE["value"] = mixin_key
        WBI_MIXIN_KEY_CACHE["expires_at"] = expires_at
    persist_wbi_mixin_key(mixin_key, expires_at)


def load_persisted_wbi_mixin_key(max_age_seconds=WBI_MIXIN_KEY_STALE_TTL_SECONDS):
    try:
        payload = json.loads(default_wbi_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("value")
    if not isinstance(value, str) or len(value) != 32:
        return None
    try:
        updated_at = float(payload.get("updated_at") or 0)
    except (TypeError, ValueError):
        return None
    if updated_at <= 0 or time.time() - updated_at > max_age_seconds:
        return None
    return value


def persist_wbi_mixin_key(mixin_key, expires_at):
    if not mixin_key:
        return
    path = default_wbi_cache_path()
    payload = {
        "value": mixin_key,
        "expires_at": expires_at,
        "updated_at": time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        return
