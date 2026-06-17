# bilibili-comment-danmaku-tool

本地运行的 Bilibili 评论、楼中楼、弹幕归档和查看工具。

项目由 Python HTTP 服务、SQLite 存储、React/Vite 前端和 Windows 免安装打包脚本组成。仓库只保存源码、测试和配置；`data/`、`logs/`、`dist/`、`release/`、Cookie、数据库和构建产物都不提交。

## 当前结构

- 默认服务地址：`http://127.0.0.1:8001/`，端口占用时自动尝试后续空闲端口。
- 新数据结构：每个视频一个 SQLite 数据库，路径为 `data/databases/<UP主>/<BVID>.db`。
- `data/comment_danmaku.db` 不是新结构的必需主库；页面里的 `main` 是聚合视图标识，不代表必须存在物理主数据库。
- `data/cookie.txt` 可选；缺失时按匿名请求运行。需要登录态时，在页面登录状态里扫码登录或导入 Cookie。
- Windows release 包根目录只保留一个可见 exe，运行时依赖放在 `_internal/`，数据和日志放在 `data/`、`logs/`。

## 快速运行

```powershell
pnpm install
pnpm build
pnpm server
```

开发模式：

```powershell
pnpm server
pnpm dev
```

Vite 会把 `/api` 代理到 `http://127.0.0.1:8001`。

## 常用命令

```powershell
pnpm test            # 编码检查 + 后端 unittest + 前端 Vitest
pnpm test:backend
pnpm test:frontend
pnpm build           # 测试 + TypeScript 检查 + Vite 构建
pnpm package:windows # 构建 Windows 免安装包
```

CLI：

```powershell
python backend/app_cli.py fetch-video BV1xx411c7mD
python backend/app_cli.py list-space https://space.bilibili.com/1538787344 --max-videos 3
python backend/app_cli.py archive-space https://space.bilibili.com/1538787344 --max-videos 1
```

打包后的 exe 也支持 CLI：

```powershell
.\release\bilibili-comment-danmaku-tool\bilibili-comment-danmaku-tool.exe cli fetch-video BV1xx411c7mD
.\release\bilibili-comment-danmaku-tool\bilibili-comment-danmaku-tool.exe cli list-space https://space.bilibili.com/1538787344 --max-videos 3
```

## 测试重点

- CI 没有 `data/cookie.txt`，测试不能依赖本机 Cookie。
- 后端测试覆盖无 Cookie 匿名路径、单视频单库、UP 主目录、任务队列恢复、导入导出、分页和打包脚本。
- 前端测试覆盖 API 请求、AbortSignal、数据库作用域、组件渲染和大列表行为。
- 只改文档时通常不需要跑完整 `pnpm build`；改代码、打包、workflow 时必须跑相关测试。

## GitHub Release

自动发布规则：

1. 只有合并到 `main` 的 merge commit 会自动发布。
2. 只有前后端、后端、脚本、依赖文件变更才触发；只改 README、AGENTS、普通文档不发布。
3. workflow 自动递增稳定版本 tag，例如 `v1.0.2` -> `v1.0.3`。
4. Windows 包会上传到 GitHub Release。

也可以手动运行 `Release` workflow，输入版本号和目标分支。

## 项目目录

```text
backend/     Python 服务、抓取、任务队列、SQLite 存储、控制 API
frontend/    Vite + React + TypeScript 页面
scripts/     启动、编码检查、Nuitka 打包脚本
tests/       后端 unittest、前端 Vitest、覆盖说明
assets/      应用图标等静态资源
```

## 设计约束

- 本地工具优先，不按公网服务设计。
- SQLite 是事实来源；新归档默认一视频一库。
- 长任务必须可观察、可暂停、可停止、可恢复。
- 评论刷新保留历史缺失评论，不因为本次 API 未返回就物理删除。
- 弹幕刷新遇到远端 0 条时，不覆盖已有本地弹幕。
- 日志必须脱敏，不能记录 Cookie、token、密码或完整敏感正文。
- 源码必须是 UTF-8 无 BOM；终端显示乱码不等于文件编码错，先跑 `pnpm test:encoding`。
