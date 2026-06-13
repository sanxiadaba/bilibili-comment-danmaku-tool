# bilibili-comment-danmaku-tool

本地运行的 Bilibili 评论、楼中楼、弹幕归档和查看工具。

它把数据保存到本机 SQLite，通过 Python HTTP 服务提供 API 和 React 页面。仓库只保存源码和配置，不保存 cookie、数据库、日志、依赖或构建产物。

## 功能

- 按视频 URL 或 BV 号归档评论和弹幕。
- 把 UP 主全部视频加入归档任务队列。
- 支持任务暂停、继续、停止、重试和清空记录。
- 服务重启后可恢复持久化任务。
- 内置登录态管理，支持扫码登录、粘贴 Cookie、导入 Cookie 文件和清除登录态。
- 查看视频库、评论、弹幕、统计和详情。
- 独立刷新评论和弹幕。
- 刷新评论时保留“本次未返回”的历史评论。
- JSON / SQLite 导入导出。
- 通过 `/api/v1/control` 被其它本地程序调用。

## 环境

- Python 3.11+
- pnpm
- 可选：`data/cookie.txt`，用于 Bilibili 登录态访问

## 安装运行

```powershell
pnpm install
pnpm build
pnpm server
```

`pnpm server` 会先停止本机 `127.0.0.1:8000` 上的旧进程，再用同一个端口启动当前版本。

访问：

```text
http://127.0.0.1:8000/
```

开发模式：

```powershell
pnpm server
pnpm dev
```

Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

## 本地数据

```text
data/comment_danmaku.db       默认 SQLite 数据库
data/cookie.txt               可选 Bilibili cookie
data/databases/               导入或热插拔数据库
data/exports/                 本地导出目录
logs/app.jsonl                结构化运行日志
dist/                         前端构建产物
```

这些路径均被 Git 忽略。

## 常用命令

```powershell
pnpm test            # 后端 + 前端测试
pnpm test:encoding
pnpm test:backend
pnpm test:frontend
pnpm build           # 测试、类型检查、Vite 构建
pnpm server          # Python 服务，127.0.0.1:8000
pnpm dev             # Vite 开发服务
pnpm fetch           # 单视频 CLI 抓取辅助
```

Python 编译检查：

```powershell
python -B -m py_compile backend/server.py backend/http_utils.py backend/fetch_bilibili_comment_danmaku.py backend/bilibili_comment_danmaku/storage.py backend/bilibili_comment_danmaku/danmaku.py backend/bilibili_comment_danmaku/scraper.py backend/bilibili_comment_danmaku/wbi.py backend/bilibili_comment_danmaku/url_utils.py backend/bilibili_comment_danmaku/__init__.py backend/task_queue.py backend/space_archive.py backend/video_tasks.py
```

## 控制 API

外部本地集成优先使用稳定控制命名空间：

```text
GET  /api/v1/control
GET  /api/v1/control/openapi.json
GET  /api/v1/control/status
GET  /api/v1/control/progress
POST /api/v1/control/actions
```

示例：

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

动作元数据和 schema 来自 `backend/control_api.py`。

## 项目结构

```text
backend/       Python 服务、任务队列、Bilibili 抓取、SQLite 存储
frontend/      Vite + React + TypeScript 页面
tests/         后端 unittest 和前端 Vitest
AGENTS.md      agent 开发规则
```

## 设计原则

- 本地优先：不要把服务直接暴露到公网。
- SQLite 优先：迁移必须兼容用户已有数据。
- 单一路径：有维护良好的主路径时，删除旧脚本和重复抽象。
- 任务可观测：长任务必须能通过进度和队列 API 查看。
- 不漂移秘密：cookie、数据库、日志、构建产物永不提交。
- 编码统一：源码必须是 UTF-8 无 BOM，`pnpm test:encoding` 会拦截 BOM 和典型 mojibake 乱码。
