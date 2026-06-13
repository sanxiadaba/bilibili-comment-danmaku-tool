# Agent Handbook

This project is a local Bilibili comment and danmaku archive tool. Keep it small, explicit, and boring. When a choice is unclear, prefer the option with fewer moving parts.

## Non-Negotiables

- Work on a branch for every requested change. Start from `main`, push the branch, and merge only after the user explicitly asks.
- Git and GitHub traffic should use `http://127.0.0.1:7890`.
- Bilibili scraping should not use the proxy by default.
- Never commit local data or secrets: `data/`, `logs/`, `dist/`, `node_modules/`, `cookie.txt`, `*.db`, `*.sqlite*`, `__pycache__/`, `*.pyc`, `.env*`.
- Before committing, run `git status --short --ignored` and confirm generated or sensitive files are only shown as ignored.
- Prefer `pnpm` for frontend commands and `uv` when Python dependency management is needed.

## Commands

```powershell
pnpm install
pnpm test
pnpm build
pnpm server
pnpm dev
```

Focused checks:

```powershell
pnpm test:backend
pnpm test:frontend
python -B -m py_compile backend/server.py backend/fetch_bilibili_comment_danmaku.py backend/bilibili_comment_danmaku/storage.py backend/bilibili_comment_danmaku/danmaku.py backend/bilibili_comment_danmaku/scraper.py backend/bilibili_comment_danmaku/url_utils.py backend/bilibili_comment_danmaku/__init__.py backend/task_queue.py backend/space_archive.py backend/video_tasks.py
git status --short --ignored
```

Local app:

```text
http://127.0.0.1:8000/
```

## Shape Of The Code

```text
backend/
  server.py                         HTTP API, static files, control dispatch
  task_queue.py                     persistent in-memory task queue
  video_tasks.py                    single-video parse tasks
  space_archive.py                  UP-owner archive tasks
  progress_state.py                 progress snapshot and polling state
  database_registry.py              database import/export/catalog paths
  control_api.py                    /api/v1/control capability metadata
  bilibili_comment_danmaku/
    scraper.py                      video info, comments, WBI signing
    danmaku.py                      danmaku XML and like counts
    storage.py                      SQLite schema, persistence, read models
    archive.py                      JSON/SQLite archive import/export
    url_utils.py                    BV parsing

frontend/src/
  pages/                            route-level state and layouts
  components/comments/              comment UI
  components/danmaku/               danmaku UI
  components/video-library/         library, tasks, database management
  components/ui/                    small shared UI primitives
  api/client.ts                     typed fetch wrappers
  hooks/                            React hooks
  lib/                              pure helpers
  types.ts                          frontend/backend JSON contracts

tests/
  backend/                          unittest coverage for storage, scraping, queue, control API
  frontend/                         Vitest coverage for API, UI components, helpers
```

## Core Invariants

- SQLite is the source of truth. The default database is `data/comment_danmaku.db`.
- `data/comments.db` may be copied forward only as a compatibility migration when the default DB is missing.
- Comment refresh marks old comments as `is_deleted = 1` before upserting newly returned comments. Do not delete missing comments during refresh.
- Danmaku refresh must not replace existing local danmaku with an empty remote result.
- Task state must survive service restart when persistence is enabled. Pause/stop flags must be visible inside long-running fetch loops.
- `/api/videos` is paginated. Do not restore full-library aggregation on the homepage path.
- Export formats are exclusive: JSON export writes JSON only; SQLite export writes DB only.
- `user_hash` is internal. Do not show it in the UI.
- Danmaku colors should be shown as readable names and swatches, not raw hashes.

## Public Interfaces

UI-oriented endpoints live under `/api/*`.

Automation should prefer:

```text
GET  /api/v1/control
GET  /api/v1/control/openapi.json
GET  /api/v1/control/status
GET  /api/v1/control/progress
POST /api/v1/control/actions
```

Supported control actions are declared in `backend/control_api.py`. Keep that file as the contract source instead of duplicating detailed API docs elsewhere.

## Frontend Rules

- Keep page files responsible for orchestration; move reusable display logic into domain components.
- Use `VirtualList` for large comments or danmaku lists.
- Keep control surfaces dense and local-tool-like. Avoid marketing sections.
- Use lucide icons for buttons when there is a standard icon.
- Text must fit on small screens. Use `min-w-0`, wrapping, and overflow rules deliberately.

## Backend Rules

- Prefer standard-library Python unless a dependency clearly removes more code than it adds.
- Keep Bilibili client behavior centralized in `scraper.py` and `danmaku.py`.
- Keep storage migrations compatible with existing user databases.
- Add indexes only for observed query paths.
- Log important API/task events through `app_logging.py`; do not log cookies, tokens, or raw secrets.

## Testing Expectations

- Small doc-only changes: at least inspect `git diff` and `git status --short --ignored`.
- Code changes: run `pnpm test` or the relevant focused tests plus Python compile.
- Frontend behavior/layout changes: run `pnpm test:frontend` and verify the local page in a browser when practical.
- Build-affecting changes: run `pnpm build`.

## Git Flow

```powershell
git status --short --branch
git checkout main
git pull --ff-only origin main
git checkout -b codex/<short-purpose>
# edit, test
git status --short --ignored
git add <files>
git commit -m "<imperative summary>"
git push origin codex/<short-purpose>
```

Only merge after the user says to merge. After merge, delete the feature branch locally and remotely.
