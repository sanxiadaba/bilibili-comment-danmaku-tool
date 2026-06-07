# bilibili-comment-danmaku-tool

一个本地运行的 Bilibili 评论与弹幕归档、刷新、可视化工具。

项目用于把指定视频的评论、楼中楼回复、弹幕和统计信息保存到本地 SQLite 数据库，并通过 React 界面查看、筛选和分析。仓库只保存源码和配置，不保存 cookie、数据库、日志、依赖和构建产物。

## 功能

- 解析 Bilibili 视频 URL 或 BV 号。
- 抓取并归档评论、楼中楼回复和弹幕。
- 将数据保存到本地 SQLite 数据库 `data/comments.db`。
- 查看视频库、评论列表、评论详情、评论时间分布、地区分布、活跃用户和热门评论。
- 查看弹幕列表、弹幕时间分布、模式分布、颜色分布、重复弹幕、点赞数和 UP 主弹幕标记。
- 评论与弹幕可以独立刷新。
- 抓取评论和弹幕时显示实时进度、百分比、阶段说明和关键统计。
- 刷新评论时保留“本次未返回”的历史评论，便于观察评论状态变化。

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
- 默认 SQLite 数据库为 `data/comments.db`。
- 旧数据库或人工备份可放在 `data/backups/`。
- 本地日志放在 `logs/`。
- `data/`、`logs/`、`dist/`、`node_modules/` 和缓存文件都不会提交到 Git。

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

构建前端：

```powershell
pnpm build
```

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

