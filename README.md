# bilibili-comment-danmaku-tool

一个本地运行的 Bilibili 评论与弹幕归档、刷新、可视化工具。

项目用于把指定视频的评论、楼中楼回复、弹幕和统计信息保存到本地 SQLite 数据库，并通过 React 界面查看、筛选和分析。仓库只保存源码和配置，不保存 cookie、数据库、日志、依赖和构建产物。

## 功能

- 解析 Bilibili 视频 URL 或 BV 号。
- 抓取并归档评论、楼中楼回复和弹幕。
- 将数据保存到本地 SQLite 数据库 `data/comment_danmaku.db`。
- 查看视频库、评论列表、评论详情、评论时间分布、地区分布、活跃用户和热门评论。
- 查看弹幕列表、弹幕时间分布、模式分布、颜色分布、重复弹幕、点赞数和 UP 主弹幕标记。
- 评论与弹幕可以独立刷新。
- 抓取评论和弹幕时显示实时进度、百分比、阶段说明和关键统计。
- 刷新评论时保留“本次未返回”的历史评论，便于观察评论状态变化。
- 评论和弹幕大列表使用虚拟滚动，数据量较大时也能降低页面加载和滚动卡顿。

## 目录

```text
.
├── backend/          # Python 后端、Bilibili 抓取、SQLite 读写
├── frontend/         # Vite + React + TypeScript 前端
├── data/             # 本地数据库、cookie、备份，ignored，不提交
├── logs/             # 本地运行日志，ignored，不提交
├── dist/             # 前端构建产物，ignored，不提交
├── package.json      # 根目录统一命令入口
├── pnpm-lock.yaml
├── README.md
└── AGENTS.md         # 面向其它 agent 的详细开发手册
```

## 环境要求

- Python 3.11+
- pnpm
- 如需完整访问评论数据，可能需要自行提供 Bilibili cookie

## 本地数据

本仓库不包含本地数据和凭据。

- Cookie 放在 `data/cookie.txt`。
- 默认 SQLite 数据库为 `data/comment_danmaku.db`。
- 旧数据库或人工备份可放在 `data/backups/`。
- 本地日志放在 `logs/`，其中 `logs/app.jsonl` 是结构化事件日志。
- `data/`、`logs/`、`dist/`、`node_modules/` 和缓存文件都不会提交到 Git。

## 日志

服务启动后会写入结构化 JSONL 日志：

```text
logs/app.jsonl
```

日志覆盖服务启动、HTTP 请求、API 成功/失败、抓取进度、评论/弹幕刷新、空弹幕保护、前端用户操作和前端 API 请求结果。每行是一条 JSON 事件，包含时间、级别、事件名、请求 ID、状态码、耗时和相关业务字段，便于后续排查和分析。

日志写入使用有上限的后台队列，默认单文件 10MB、保留 10 个轮转文件、队列 10000 条。日志量过大时，服务不会因为日志写盘阻塞请求；低优先级日志会被计数丢弃，高优先级 warning/error 会尽量保留。`/api/health` 会返回日志队列、轮转和丢弃计数状态，便于长时间运行后检查日志系统是否健康。

日志文件属于本地运行数据，不会提交到 Git。

## 本地运行

安装依赖并构建前端：

```powershell
pnpm install
pnpm build
```

启动本地服务：

```powershell
pnpm server
```

然后访问：

```text
http://127.0.0.1:8000/
```

## 外部控制 API

本服务也可以被其它本地程序或接口直接调用。第三方集成建议使用稳定命名空间：

```text
http://127.0.0.1:8000/api/v1/control
```

能力发现：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/control
```

统一动作入口：

```text
POST /api/v1/control/actions
```

请求体格式：

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

常用动作：

- `videos.parse`：抓取单个视频评论和弹幕。
- `comments.refresh`：刷新指定视频评论。
- `danmaku.refresh`：刷新指定视频弹幕。
- `space.archive`：把 UP 主全部视频归档任务加入队列。
- `archive.export`：导出视频、视频集合或 UP 主归档。
- `databases.import`：从本机路径导入 SQLite 数据库或 JSON 归档。

也可以直接调用 REST 风格端点：

```text
POST /api/v1/control/videos/parse
POST /api/v1/control/comments/refresh
POST /api/v1/control/danmaku/refresh
POST /api/v1/control/space/archive
POST /api/v1/control/archive/export
POST /api/v1/control/databases/import
GET  /api/v1/control/status
GET  /api/v1/control/progress
GET  /api/v1/control/videos?db_id=main
GET  /api/v1/control/comments?bvid=BV...&db_id=main
GET  /api/v1/control/danmaku?bvid=BV...&db_id=main
```

导出格式是互斥的：`format=json` 只生成 JSON 文件，`format=sqlite` 只生成 SQLite 数据库文件。长耗时抓取任务可通过 `/api/v1/control/progress` 或 `/api/v1/control/status` 查询实时进度和队列状态。

## 开发模式

启动后端服务：

```powershell
pnpm server
```

另开一个终端启动 Vite：

```powershell
pnpm dev
```

Vite 开发服务会把 `/api` 代理到：

```text
http://127.0.0.1:8000
```

## 常用检查

运行完整测试：

```powershell
pnpm test
```

测试覆盖后端 BV 解析、弹幕 XML 解析、SQLite 评论/弹幕保存读取、评论刷新保留未返回评论、日志敏感字段过滤和队列背压；前端覆盖评论筛选排序、评论内容拆分、弹幕排序、时间桶、模式/颜色统计和重复弹幕统计。

构建前端：

```powershell
pnpm build
```

`pnpm build` 会先执行完整测试，测试通过后才会继续 TypeScript 检查和 Vite 构建。

检查 Python 语法：

```powershell
python -B -m py_compile backend\server.py backend\fetch_bilibili_comment_danmaku.py backend\bilibili_comment_danmaku\storage.py backend\bilibili_comment_danmaku\danmaku.py backend\bilibili_comment_danmaku\scraper.py backend\bilibili_comment_danmaku\url_utils.py backend\bilibili_comment_danmaku\__init__.py
```

检查 Git 状态和忽略文件：

```powershell
git status --short --ignored
```

确认 `data/`、`logs/`、`dist/`、`node_modules/`、cookie、数据库、日志和缓存都没有进入暂存区。

## Agent 文档

其它 agent 接手开发时，请优先阅读：

```text
AGENTS.md
```

该文档包含项目架构、数据流、后端 API、SQLite 表结构、前端页面职责、开发流程、验证清单、目录整理原则和已知风险。


