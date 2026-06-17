# Agent 开发手册

这个项目是本地 Bilibili 评论、楼中楼、弹幕归档工具。改动要小、准、可验证；不要把旧结构、旧端口或本机环境假设写回代码。

## 硬规则

- 每个问题从 `main` 新建分支；用户明确要求后才合并回 `main`。
- Git / GitHub 使用代理：`http://127.0.0.1:7890`。
- 前端命令用 `pnpm`；Python 环境/工具需要时优先 `uv`。
- 不提交 `data/`、`logs/`、`dist/`、`release/`、`node_modules/`、Cookie、数据库、`.env`、缓存文件。
- 提交前看 `git status -sb`，确认没有误带本地数据。
- 源码必须是 UTF-8 无 BOM；PowerShell 显示中文乱码不等于文件损坏，先跑 `pnpm test:encoding`。

## 当前事实

- 默认服务端口是 `8001`，占用时自动递增，不要再写回 `8000`。
- 新归档是一视频一库：`data/databases/<UP主>/<BVID>.db`。
- 页面/API 中的 `main` 是聚合视图 id，不代表必须有 `data/comment_danmaku.db`。
- CI 没有 `data/cookie.txt`；代码和测试必须支持无 Cookie 匿名运行。
- 需要登录态时，UI 走登录状态管理；CLI 可传 `--cookie` 或 `--cookie-file`。
- Windows 包不是 onefile；根目录只放一个可见 exe，依赖在 `_internal/`，运行数据在 `data/`，日志在 `logs/`。

## 常用命令

```powershell
pnpm test
pnpm test:backend
pnpm test:frontend
pnpm build
pnpm server
pnpm dev
pnpm package:windows
```

本地地址通常是：

```text
http://127.0.0.1:8001/
```

## 测试纪律

- 不要让测试依赖本机 Cookie、真实数据库、已有 release 目录或网络状态。
- 后端新增行为优先补 unittest；前端行为补 Vitest。
- 单视频单库、无 Cookie、端口递增、release workflow、CLI、打包脚本都已有回归测试，改相关逻辑时同步更新。
- 影响构建、打包、workflow 时跑 `pnpm build`；只改文档时至少检查 diff 和编码。
- 真实 UP 主 `https://space.bilibili.com/1538787344` 可用于手动验证，不放进默认单元测试。

## Release workflow

- 自动发布只在合并到 `main` 的 merge commit 上发生。
- 只改 README、AGENTS、普通文档不应触发发布。
- workflow action 版本要避免 Node 20 警告；当前使用 Node 24 系列 action。
- `setup-uv` 没有 Python 依赖锁文件时关闭 cache，避免无效缓存警告。
- 发布失败先看真实失败步骤，不要被后续“dist 未生成”这类连锁错误误导。

## 后端注意

- Bilibili HTTP 逻辑集中在 `scraper.py`、`danmaku.py`、`wbi.py`。
- SQLite schema/migration 必须兼容用户已有数据。
- 长任务必须能暂停、停止、恢复，并通过进度/队列 API 可观察。
- 评论刷新保留“本次未返回”的历史评论；弹幕刷新不能用远端空结果覆盖本地已有弹幕。
- 日志走 `app_logging.py`，敏感字段必须脱敏。

## 前端注意

- API 封装在 `frontend/src/api/client.ts`；状态变更请求必须带本地防护 header。
- 页面切库、路由、筛选时注意取消旧请求，避免慢响应覆盖新状态。
- 大列表继续使用分页/虚拟滚动，不要一次性拉全量详情。
- UI 是工具型界面，保持紧凑、清晰、可扫描。

## Git 流程

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/<short-purpose>
# edit, test
git status -sb
git add <files>
git commit -m "<imperative summary>"
git push origin codex/<short-purpose>
```

用户确认合并后，再合并到 `main`、推送、删除本地和远程分支。
