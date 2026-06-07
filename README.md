# bilibili-comment-danmaku-tool

一个本地运行的 Bilibili 评论与弹幕归档、刷新、可视化工具。

它可以解析 Bilibili 视频链接或 BV 号，将评论、楼中楼回复、弹幕和相关统计保存到本地 SQLite 数据库，并通过 Vite + React 界面进行浏览、筛选和分析。

## 功能

- 解析 Bilibili 视频 URL 或 BV 号。
- 抓取并归档评论、楼中楼回复和弹幕。
- 将数据保存到本地 SQLite 数据库 `comments.db`。
- 查看视频库、评论列表、评论详情、评论时间分布、地区分布、活跃用户和热门评论。
- 查看弹幕列表、弹幕时间分布、模式分布、颜色分布、重复弹幕、点赞数和 UP 主弹幕标记。
- 评论与弹幕可以独立刷新。
- 抓取评论和弹幕时显示实时进度。
- 刷新评论时保留“本次未返回”的历史评论，便于观察评论状态变化。

## 环境要求

- Python 3.11+
- pnpm
- 如需完整访问评论数据，可能需要自行提供 Bilibili cookie

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

## Cookie 与本地数据

本仓库不包含本地数据和凭据。

- 如需登录态访问，请自行在项目根目录放置 `cookie.txt`。
- 程序会在本地创建和读取 `comments.db`。
- `cookie.txt`、SQLite 数据库、日志、构建产物、缓存和依赖目录都不会提交到 Git。

## 常用检查

构建前端：

```powershell
pnpm build
```

检查 Python 语法：

```powershell
python -B -m py_compile server.py fetch_bilibili_comments.py bilibili_comments\storage.py bilibili_comments\danmaku.py bilibili_comments\scraper.py bilibili_comments\url_utils.py bilibili_comments\__init__.py
```

检查 Git 状态和忽略文件：

```powershell
git status --short --ignored
```

## 面向 Agent 的开发文档

其它 agent 接手开发时，请优先阅读：

```text
AGENTS.md
```

该文档包含项目架构、数据流、后端 API、SQLite 表结构、前端页面职责、开发流程、验证清单和已知风险。
