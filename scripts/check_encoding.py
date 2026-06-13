from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CHECK_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ts",
    ".tsx",
}
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "data",
    "dist",
    "logs",
    "node_modules",
    "__pycache__",
}
MOJIBAKE_MARKERS = (
    "鎶",
    "瑙",
    "鏁",
    "闃",
    "绠",
    "寮",
    "瀵",
    "鍔",
    "鏂",
    "鏈",
    "鏃",
    "杩",
    "櫥",
    "彇",
    "浠",
    "棰",
    "搴",
    "厤",
    "缃",
    "猔",
    "�",
)


def iter_source_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in CHECK_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def main():
    errors = []
    for path in iter_source_files():
        rel = path.relative_to(ROOT)
        if rel == Path("scripts/check_encoding.py"):
            continue
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"{rel}: contains UTF-8 BOM")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{rel}: is not valid UTF-8 ({exc})")
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in MOJIBAKE_MARKERS):
                errors.append(f"{rel}:{line_no}: possible mojibake: {line.strip()[:120]}")

    if errors:
        print("Encoding check failed:")
        for item in errors[:80]:
            print(f"  {item}")
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more")
        return 1
    print("Encoding check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
