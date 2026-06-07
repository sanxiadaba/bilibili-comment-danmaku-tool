# bilibili-comment-danmaku-tool

A local Bilibili comments and danmaku visualizer. It can archive comments and danmaku into a local SQLite database, refresh them independently, and inspect the results with a Vite + React interface.

## Features

- Parse a Bilibili video URL or BV id.
- Store comments and danmaku locally in SQLite.
- View comment timelines, locations, active users, liked comments, deleted/missing comments, and comment details.
- View danmaku timelines, modes, colors, repeated text, likes, and danmaku details.
- Refresh comments and danmaku separately with live progress.

## Requirements

- Python 3.11+
- pnpm
- A Bilibili cookie file if you need authenticated comment access

## Setup

```powershell
pnpm install
pnpm build
pnpm server
```

Then open:

```text
http://127.0.0.1:8000/
```

## Cookie And Local Data

This repository does not include local data or credentials.

- Put your own Bilibili cookie in `cookie.txt` when needed.
- The app creates and reads `comments.db` locally.
- `cookie.txt`, SQLite databases, logs, build output, caches, and dependencies are ignored by git.

## Development

```powershell
pnpm dev
pnpm build
python -B -m py_compile server.py bilibili_comments\storage.py bilibili_comments\danmaku.py bilibili_comments\scraper.py
```
