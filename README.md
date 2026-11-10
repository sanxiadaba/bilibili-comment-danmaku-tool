# bilibili-comment-danmaku-tool

本地运行的 Bilibili 评论、楼中楼、弹幕归档与查看工具。Python 标准库后端 + SQLite + React/Vite 前端，附带 Windows 免安装打包脚本。

## 运行

```powershell
pnpm install
pnpm build        # 编码检查 + 测试 + TypeScript 检查 + Vite 构建
pnpm server       # http://127.0.0.1:8001/，端口被占用时自动顺延
```

开发模式（Vite 代理 `/api` 到后端，实际端口从 `data/.server-port` 读取）：

```powershell
pnpm server
pnpm dev
```

## 常用命令

```powershell
pnpm test              # 编码检查 + 后端 unittest + 前端 Vitest
pnpm test:backend
pnpm test:frontend
pnpm build:dist        # 只做 tsc + vite build
pnpm package:windows   # 构建 Windows 免安装包到 release/
```

CLI（打包后的 exe 用 `... .exe cli <命令>`）：

```powershell
python backend/app_cli.py fetch-video BV1xx411c7mD
python backend/app_cli.py list-space https://space.bilibili.com/1538787344 --max-videos 3
python backend/app_cli.py archive-space https://space.bilibili.com/1538787344 --max-videos 1
```

## 数据位置

- 一视频一库：`data/databases/<UP主>/<BVID>.db`；页面里的 `main` 是聚合视图，不是物理数据库。
- `data/comment_danmaku.db` 是旧版单库文件；启动时会自动迁移到新结构并改名备份。
- Cookie（可选）：`data/cookie.txt`。缺失时匿名运行；需要登录态时在页面「登录态」里扫码或导入。
- 日志：`logs/app.jsonl`，敏感字段已脱敏。

Windows 包解压后根目录只有一个 exe，依赖在 `_internal/`，运行数据在 `data/`、`logs/`。

## 行为约定

- 评论刷新保留本次未返回的历史评论；远端返回数量明显偏小时拒绝覆盖，需要 `force=1` 才覆盖。
- 弹幕刷新遇到远端 0 条时保留已有本地弹幕。
- 长任务（UP 主归档、单视频解析、删除）进队列，可暂停、恢复、停止。
- 评论/弹幕刷新在请求线程内执行，可通过「停止抓取」在下一个分页退出。
- 只允许绑定本机地址；没有鉴权，不要暴露到局域网。

## 测试

后端 249 个 unittest、前端 72 个 Vitest，在 Windows 与 Linux 上都能跑（CI 用 ubuntu）。测试不依赖本机 Cookie、真实数据库或网络。

## 数据库布局

```text
backend/     HTTP 服务、抓取、任务队列、SQLite 存储
frontend/    Vite + React + TypeScript 页面
scripts/     启动、编码检查、Nuitka 打包
tests/       后端 unittest、前端 Vitest
assets/      exe 图标
```

## 发布

打 `v*` tag 或手动运行 `Release` workflow 时构建 Windows 包并发布到 GitHub Release。普通分支推送只跑 CI（包含编码检查、后端测试、前端类型检查/测试/构建），不打包。
