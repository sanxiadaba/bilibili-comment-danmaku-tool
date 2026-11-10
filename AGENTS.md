# Agent 手册

Bilibili 评论/弹幕归档工具（Python 标准库后端 + React 前端）。运行、命令、数据布局见 `README.md`，这里只写改动时必须遵守的规则。

## 硬规则

- 每个问题从 `main` 新建分支（`codex/<short-purpose>`）；用户明确同意后才合并回 `main`。
- Git / GitHub 走代理：`http://127.0.0.1:7890`。
- 前端命令用 `pnpm`；需要额外 Python 工具时用 `uv`。
- 不提交 `data/`、`logs/`、`dist/`、`release/`、`node_modules/`、Cookie、数据库、`.env`、缓存文件。
- 源码 UTF-8 无 BOM；终端显示乱码不等于文件坏，先跑 `pnpm test:encoding`。
- 提交前看 `git status -sb`，确认没有误带本地数据。

## 数据安全

- SQLite 是事实来源。改 schema 必须能在用户已有 `.db` 上跑通（`ensure_schema_if_needed`），不能丢数据。
- 写库前先确认目标记录；删除/导出一次只作用于一个具体数据库，聚合视图（`main`）要显式拒绝并要求选库。
- 用 `replace=True` 覆盖评论时传 `guard_shrink=True`：远端返回明显偏少时保留本地档案。
- 弹幕远端为空时不得覆盖已有档案；点赞数未知时保留旧值。
- 写库路径禁止一次拼接超过 SQLite 变量上限（32766）的 `IN (...)`；大批量用临时表或分批。

## 后端

- Bilibili HTTP：`scraper.py`、`danmaku.py`、`wbi.py`；`space_archive.py` 自带空间列表请求与退避。
- 长任务（UP 归档、单视频解析、删除）必须进任务队列，能暂停/恢复/停止，进度可通过 `/api/progress` 观察。
- 评论/弹幕刷新是同步请求，必须响应停止标志（`stop_checker`），冷却等待也要可中断。
- 日志走 `app_logging.py`；Cookie、token、密码一律脱敏，消息正文也要脱敏。
- 服务只绑定 loopback；没有鉴权，不要加远程访问。

## 前端

- API 封装在 `frontend/src/api/client.ts`；状态变更请求自动带 `X-Bilibili-Tool-Request` 头。
- 每个会覆盖状态的请求都要有 AbortController 或单调请求序号，慢响应不得覆盖新状态。
- 大列表用 `VirtualList` 分页/虚拟滚动，不要一次渲染全量。
- 界面是工具型界面：紧凑、可扫描、中文优先；不要加动画装饰。
- 改到界面文案、布局或主流程时，同步更新 `README.md` 和 `docs/screenshots/` 里的截图，别让文档和界面说两套话。

## 测试与 CI

- 测试不能依赖本机 Cookie、真实数据库、已有 release 目录或网络。
- 后端行为改动用 unittest 覆盖（尤其数据保护、删除、分页、任务状态）；前端行为用 Vitest。
- 改构建、打包或 workflow 时跑 `pnpm build`；只改文档至少检查 `git diff` 和编码。
- CI 用 `ubuntu-latest`，只有 tag 或手动 dispatch 才打包 Windows 包；不要引入需要 Windows runner 的日常检查。
- Release workflow 只在 tag / `workflow_dispatch` 触发；不要恢复"每次 merge 自动发版"。
