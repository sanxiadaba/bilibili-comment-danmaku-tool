# Test coverage notes

The current product shape is:

- The UI keeps `main` as the aggregate catalog view id.
- New archives are stored as one SQLite database per video under `data/databases/<owner>/<bvid>.db`.
- The legacy `data/comment_danmaku.db` file is not listed in the database catalog and is not required for the aggregate video list.

Tests that still create a temporary `comment_danmaku.db` are not automatically obsolete. Many storage/archive unit tests use that name only as a disposable SQLite fixture for low-level read/write behavior.

Regression coverage for the newer architecture lives mainly in:

- `tests/backend/test_database_registry_architecture.py`
- `tests/backend/test_task_database_layout.py`
- `tests/backend/test_desktop_packaging_release.py`
- `tests/backend/test_app_cli.py`
- `tests/frontend/api/client.test.ts`
- `tests/frontend/lib/videoLibrary.test.ts`

These tests cover single-video database placement, owner folders, aggregate listing without a physical main database, CLI defaults, desktop packaging expectations, release workflow gating, request abort propagation, browser mutation guards, and database-scoped links.
