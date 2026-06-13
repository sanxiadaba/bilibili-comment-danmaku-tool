# Agent 开发手册

这个项目是本地运行的 Bilibili 评论、楼中楼、弹幕归档和查看工具。原则很简单：少即是多，保留一条清楚的主路径，删除没有维护价值的旁路。

## 硬规则

- 每个需求先从 `main` 新建分支，提交并推送；只有用户明确说“合并”后才合并回 `main`。
- Git / GitHub 使用代理：`http://127.0.0.1:7890`。
- Bilibili 抓取默认不走代理。
- 不提交本地数据和秘密：`data/`、`logs/`、`dist/`、`node_modules/`、`cookie.txt`、`*.db`、`*.sqlite*`、`__pycache__/`、`*.pyc`、`.env*`。
- 提交前必须运行 `git status --short --ignored`，确认敏感文件只在 ignored 区域。
- 前端优先 `pnpm`；Python 依赖管理需要时优先 `uv`。

## 常用命令

```powershell
pnpm install
pnpm test
pnpm build
pnpm server
pnpm dev
```

专项检查：

```powershell
pnpm test:backend
pnpm test:frontend
python -B -m py_compile backend/server.py backend/http_utils.py backend/fetch_bilibili_comment_danmaku.py backend/bilibili_comment_danmaku/storage.py backend/bilibili_comment_danmaku/danmaku.py backend/bilibili_comment_danmaku/scraper.py backend/bilibili_comment_danmaku/wbi.py backend/bilibili_comment_danmaku/url_utils.py backend/bilibili_comment_danmaku/__init__.py backend/task_queue.py backend/space_archive.py backend/video_tasks.py
git status --short --ignored
```

本地地址：

```text
http://127.0.0.1:8000/
```

## 目录地图

```text
backend/
  server.py                         HTTP API、静态文件、控制接口调度
  http_utils.py                     JSON 请求、静态文件、HTTP 日志等基础能力
  task_queue.py                     可持久化任务队列
  video_tasks.py                    单视频抓取任务
  space_archive.py                  UP 主视频归档任务
  progress_state.py                 进度快照和轮询状态
  database_registry.py              数据库导入、导出、目录扫描
  control_api.py                    /api/v1/control 契约元数据
  bilibili_comment_danmaku/
    scraper.py                      视频信息、评论抓取编排
    wbi.py                          WBI 签名、mixin key、签名缓存
    danmaku.py                      弹幕 XML 和点赞数
    storage.py                      SQLite schema、保存、读取模型
    archive.py                      JSON / SQLite 归档导入导出
    url_utils.py                    BV 号解析

frontend/src/
  pages/                            页面级状态和布局
  components/comments/              评论领域 UI
  components/danmaku/               弹幕领域 UI
  components/video-library/         视频库、任务、数据库管理
  components/ui/                    小型通用 UI
  api/client.ts                     typed fetch 封装
  hooks/                            React hooks
  lib/                              纯函数工具
  types.ts                          前后端 JSON 契约

tests/
  backend/                          unittest
  frontend/                         Vitest
```

## 核心不变量

- SQLite 是事实来源，默认库是 `data/comment_danmaku.db`。
- 旧 `data/comments.db` 只允许在默认库缺失时自动复制迁移。
- 评论刷新时先把旧评论标为 `is_deleted = 1`，再恢复本次返回的评论；不要删除“本次未返回”的历史评论。
- 弹幕刷新遇到远端 0 条结果时，如果本地已有弹幕，必须保留旧档案。
- 任务启用持久化时，服务重启后仍要能继续运行。
- pause / stop 标记必须能被长时间抓取循环看到。
- `/api/videos` 必须分页；首页不要恢复全库聚合查询。
- 导出格式互斥：JSON 只写 JSON，SQLite 只写数据库。
- 登录态由 `backend/auth_store.py` 管理；`data/cookie.txt` 仍是本地存储文件，但 UI/API 应走登录态管理接口。
- `user_hash` 是内部字段，不在 UI 展示。
- 弹幕颜色用中文名和色块展示，不展示裸 hash。

## 公共接口

UI 接口在 `/api/*`。外部自动化优先用稳定控制接口：

```text
GET  /api/v1/control
GET  /api/v1/control/openapi.json
GET  /api/v1/control/status
GET  /api/v1/control/progress
POST /api/v1/control/actions
```

控制动作以 `backend/control_api.py` 为准。不要在文档里重复维护大段 API schema。

## 前端原则

- 页面负责串联状态和布局；可复用展示逻辑放到领域组件。
- 评论、弹幕大列表必须使用虚拟滚动。
- 工具界面保持紧凑、清晰，不做营销式页面。
- 有标准图标时用 lucide 图标。
- 移动端和窄屏必须避免文字溢出；优先使用 `min-w-0`、换行和明确的 overflow。
- 注意：`VideoLibraryPage.tsx` 存在历史中文编码损伤。重构前先单独修复编码，避免整文件重写放大问题。

## 后端原则

- 优先标准库 Python；只有依赖能明显减少复杂度时才引入。
- Bilibili HTTP 行为集中在 `scraper.py` 和 `danmaku.py`；WBI 签名基础能力放在 `wbi.py`。
- SQLite migration 必须兼容用户已有数据库。
- 只为真实查询路径加索引。
- 重要 API / 任务事件走 `app_logging.py`；不要记录 cookie、token、密码或完整敏感正文。

## 验证策略

- 文档小改：检查 diff 和 `git status --short --ignored`。
- 代码改动：运行 `pnpm test`，或相关专项测试加 Python 编译。
- 前端行为改动：运行 `pnpm test:frontend`，实际页面可用时用浏览器验一遍。
- 影响构建：运行 `pnpm build`。

## Git 流程

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

用户确认后再合并；合并后删除本地和远端分支。
