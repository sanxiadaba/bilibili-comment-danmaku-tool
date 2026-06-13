# bilibili-comment-danmaku-tool

A local tool for archiving and exploring Bilibili comments, nested replies, danmaku, and video metadata.

The app stores everything in local SQLite files and serves a React UI from a small Python HTTP server. The repository contains source code only: no cookies, databases, logs, dependencies, or build output.

## Features

- Archive one video by URL or BV id.
- Queue UP-owner archive tasks.
- Pause, resume, stop, retry, and clear tasks.
- Persist queued tasks across service restarts.
- View video library, comments, danmaku, statistics, and detail panels.
- Refresh comments and danmaku independently.
- Preserve comments that are not returned during refresh.
- Export/import archives as JSON or SQLite.
- Control the tool from other local programs through `/api/v1/control`.

## Requirements

- Python 3.11+
- pnpm
- Optional: `data/cookie.txt` for logged-in Bilibili access

## Install And Run

```powershell
pnpm install
pnpm build
pnpm server
```

Open:

```text
http://127.0.0.1:8000/
```

Development mode:

```powershell
pnpm server
pnpm dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`.

## Local Data

```text
data/comment_danmaku.db       default SQLite database
data/cookie.txt               optional Bilibili cookie
data/databases/               imported or hot-plug databases
data/exports/                 local export output
logs/app.jsonl                structured runtime log
dist/                         frontend build output
```

These paths are ignored by Git.

## Commands

```powershell
pnpm test            # backend + frontend tests
pnpm test:backend
pnpm test:frontend
pnpm build           # tests, typecheck, Vite build
pnpm server          # Python server on 127.0.0.1:8000
pnpm dev             # Vite dev server
pnpm fetch           # CLI single-video archive helper
```

Python compile check:

```powershell
python -B -m py_compile backend/server.py backend/fetch_bilibili_comment_danmaku.py backend/bilibili_comment_danmaku/storage.py backend/bilibili_comment_danmaku/danmaku.py backend/bilibili_comment_danmaku/scraper.py backend/bilibili_comment_danmaku/url_utils.py backend/bilibili_comment_danmaku/__init__.py backend/task_queue.py backend/space_archive.py backend/video_tasks.py
```

## Control API

External local integrations should prefer the stable control namespace:

```text
GET  /api/v1/control
GET  /api/v1/control/openapi.json
GET  /api/v1/control/status
GET  /api/v1/control/progress
POST /api/v1/control/actions
```

Example:

```json
{
  "action": "archive.export",
  "params": {
    "format": "json",
    "bvid": "BV1xx411c7mD",
    "db_id": "main"
  }
}
```

Action metadata and schemas are generated from `backend/control_api.py`.

## Project Map

```text
backend/       Python server, task queue, Bilibili scraping, SQLite storage
frontend/      Vite + React + TypeScript UI
tests/         backend unittest and frontend Vitest coverage
AGENTS.md      development rules for coding agents
```

## Design Principles

- Local-first. Do not expose the server to the public internet.
- SQLite-first. Keep database migrations compatible with existing user data.
- One clear path. Remove old scripts and duplicate abstractions when the app has a better maintained path.
- Observable tasks. Long-running work should be visible through progress and queue APIs.
- No secret drift. Never commit cookies, databases, logs, or generated output.
