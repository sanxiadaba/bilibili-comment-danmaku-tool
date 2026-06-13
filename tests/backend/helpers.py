import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BVID = "BV1xx411c7mD"


def make_comment(rpid, level, message, *, root="0", parent="0", mid="100", like=0, ctime=1700000000):
    return {
        "normalized": {
            "level": level,
            "rpid": str(rpid),
            "oid": "123",
            "type": 1,
            "mid": str(mid),
            "root": str(root),
            "parent": str(parent),
            "dialog": "0",
            "ctime": ctime,
            "time_iso": "2024-01-01T00:00:00+08:00",
            "time_iso_utc": "2023-12-31T16:00:00+00:00",
            "like": like,
            "rcount": 1 if level == 1 else 0,
            "count": 1 if level == 1 else 0,
            "state": 0,
            "attr": 0,
            "message": message,
            "ip_location": "Shanghai",
            "pictures": [
                {
                    "img_src": "http://i.example/a.jpg",
                    "img_width": 640,
                    "img_height": 480,
                    "img_size": 12.5,
                    "play_gif_thumbnail": False,
                }
            ]
            if level == 1
            else [],
            "emote": {
                "[doge]": {
                    "url": "http://i.example/doge.png",
                    "jump_title": "doge",
                    "meta": {"size": 1},
                    "package_id": 1,
                    "type": 1,
                }
            }
            if level == 1
            else {},
            "user": {
                "mid": str(mid),
                "uname": f"user-{mid}",
            "sex": "unknown",
                "sign": "hello",
                "avatar": "http://i.example/avatar.jpg",
                "level": 5,
            },
        },
        "raw": {},
        "replies": [],
    }


def make_archive(fetched_at, comments):
    return {
        "metadata": {
            "bvid": BVID,
            "aid": 123,
            "title": "Test video",
            "source_url": f"https://www.bilibili.com/video/{BVID}",
            "fetched_at": fetched_at,
            "sort": "like",
            "api_comment_count": len(comments),
            "top_level_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 1),
            "expected_nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "nested_comment_count": sum(1 for item in comments if item["normalized"]["level"] == 2),
            "comment_total_count": len(comments),
        },
        "video_raw": {
            "cid": "456",
            "pic": "http://i.example/pic.jpg",
            "owner": {"mid": "42", "name": "Owner", "face": "http://i.example/up.jpg"},
            "stat": {"view": 1000, "danmaku": 2, "reply": 2, "favorite": 1, "coin": 2, "share": 3, "like": 4},
            "pubdate": 1700000000,
            "desc": "desc",
            "duration": 180,
        },
        "comments": comments,
    }
