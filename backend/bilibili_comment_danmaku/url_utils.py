import re


BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")


def extract_bvid(value):
    if not value:
        raise ValueError("missing Bilibili video URL or BV id")

    match = BVID_RE.search(value.strip())
    if not match:
        raise ValueError(f"could not find a BV id in: {value}")
    return match.group(0)
