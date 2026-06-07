# Agent 开发手册

本文档面向接手本项目的其它 agent。目标是让新的 agent 不需要重新猜测架构，就能快速理解项目、定位代码、开发功能、排查问题并提交变更。

## 1. 项目定位

`bilibili-comment-danmaku-tool` 是一个本地运行的 Bilibili 评论与弹幕归档、刷新、可视化工具。

核心能力：

- 输入 Bilibili 视频链接或 BV 号，抓取视频信息、评论、楼中楼回复和弹幕。
- 将评论、用户、图片、表情、弹幕存入本地 SQLite 数据库。
- 在 React 前端中查看视频库、评论详情、评论统计、弹幕列表、弹幕时间分布、颜色分布、重复弹幕、点赞数等。
- 评论和弹幕可以独立刷新，并通过 `/api/progress` 实时显示抓取进度。
- 刷新评论时保留“本次未返回”的历史评论，用于观察评论是否被删除、折叠或接口暂时未返回。

本项目是本地工具，不是线上服务。仓库不应包含 cookie、数据库、日志、构建产物或依赖目录。

## 2. 对 agent 的硬性工作规则

### 2.1 分支规则

用户明确要求：以后每次改需求，先创建分支，用户确认可以后，再合并。

执行任何功能、修复、文档、重构类改动时：

1. 确认当前工作区是否干净：`git status --short --branch`
2. 从 `main` 新建语义清晰的分支，例如：
   - `feature/danmaku-progress`
   - `fix/comment-layout-overlap`
   - `docs/agent-handbook`
   - `cleanup/slim-file-structure`
3. 在分支上提交并推送。
4. 告诉用户分支名、提交、验证结果和 GitHub 链接。
5. 等用户明确回复“合并”或同义确认后，才合并进 `main`。

不要在未经确认时把分支合并到 `main`。

### 2.2 Git 与代理

- Git 代理使用：`http://127.0.0.1:7890`
- 现有 Git 身份：
  - name: `jun`
  - email: `2190165626@qq.com`
- GitHub 仓库：
  - `https://github.com/sanxiadaba/bilibili-comment-danmaku-tool`

注意：当前机器上 GitHub CLI 可能安装在 `C:\Program Files\GitHub CLI\gh.exe`，但不一定在 `PATH` 中。若 `gh` 找不到，可使用完整路径。

### 2.3 敏感文件与本地文件

禁止提交：

- `cookie.txt`
- `comments*.db`
- `*.sqlite`
- `*.sqlite3`
- `dist/`
- `node_modules/`
- `__pycache__/`
- `*.pyc`
- `*.tsbuildinfo`
- `server.log`
- `server.err`
- `.env*`

提交前必须执行：

```powershell
git status --short --ignored
```

确认敏感数据和生成物都在 `!!` ignored 区域，不能出现在 staged changes 中。

### 2.4 网络与 Bilibili 访问

用户曾明确说明：访问 B 站不需要走 `7890` 代理。

当前代码现状：

- Web 服务 `server.py` 调用 `scrape_comments` 和 `scrape_danmaku` 时没有传 `use_proxy=True`，因此默认不走代理。
- CLI 脚本 `fetch_bilibili_comments.py` 当前默认 `use_proxy=not args.no_proxy`，也就是默认走代理；若使用 CLI 且希望不走代理，需要传 `--no-proxy`。
- 如果要统一行为，应单独开分支修改 CLI 默认值，并提醒用户该行为变化。

## 3. 技术栈

后端：

- Python 标准库为主。
- HTTP 服务：`http.server.ThreadingHTTPServer`
- 数据库：SQLite，使用 `sqlite3`
- 网络请求：`urllib.request`
- XML 解析：`xml.etree.ElementTree`

前端：

- Vite
- React 19
- TypeScript
- Tailwind CSS
- lucide-react 图标
- 包管理：`pnpm`

构建配置：

- `vite.config.ts`：Vite + React，开发代理 `/api -> http://127.0.0.1:8000`
- `tsconfig.json`：前端源码和 Vite 配置 TypeScript 检查
- `tailwind.config.ts`：主题色、阴影、字体
- `postcss.config.js`：Tailwind + Autoprefixer

## 4. 常用命令

安装依赖：

```powershell
pnpm install
```

构建前端：

```powershell
pnpm build
```

启动后端静态服务：

```powershell
pnpm server
```

启动 Vite 开发服务：

```powershell
pnpm dev
```

Python 语法检查：

```powershell
python -B -m py_compile server.py fetch_bilibili_comments.py bilibili_comments\storage.py bilibili_comments\danmaku.py bilibili_comments\scraper.py bilibili_comments\url_utils.py bilibili_comments\__init__.py
```

访问地址：

```text
http://127.0.0.1:8000/
```

开发模式常见组合：

1. 一个终端运行后端：`pnpm server`
2. 一个终端运行前端：`pnpm dev`
3. 前端通过 Vite proxy 请求后端 `/api`

生产/本地单服务模式：

1. 执行 `pnpm build`
2. 执行 `pnpm server`
3. `server.py` 从 `dist/` 提供静态页面

## 5. 目录结构

```text
.
├── AGENTS.md                     # agent 接手和开发手册
├── README.md                     # 面向用户的项目说明
├── server.py                     # Python HTTP API + 静态文件服务
├── fetch_bilibili_comments.py    # CLI 抓取入口
├── bilibili_comments/
│   ├── __init__.py               # Python 包导出
│   ├── url_utils.py              # BV 号提取
│   ├── scraper.py                # 评论抓取、WBI 签名、评论归一化
│   ├── danmaku.py                # 弹幕 XML 抓取、点赞数抓取、弹幕解析
│   └── storage.py                # SQLite schema、保存、读取、聚合
├── src/
│   ├── main.tsx                  # React 挂载入口
│   ├── App.tsx                   # 极简路由入口
│   ├── types.ts                  # 前后端数据契约 TypeScript 类型
│   ├── styles.css                # Tailwind 入口和全局样式
│   ├── api/                      # 前端 API 请求封装
│   ├── hooks/                    # React hooks
│   ├── pages/                    # 页面级组件
│   ├── lib/
│   │   ├── utils.ts              # 评论过滤、排序、统计、格式化工具
│   │   └── csv.ts                # CSV 导出转义
│   └── components/
│       ├── common.tsx            # 页面通用展示组件
│       ├── comments/             # 评论列表、详情、图表组件
│       ├── danmaku/              # 弹幕列表、详情、图表、工具
│       └── ui/                   # 基础 UI 小组件
├── package.json
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
└── postcss.config.js
```

本地会出现但不提交：

```text
comments.db
comments.db-shm
comments.db-wal
comments_legacy.db
comments_before_deleted_restore_*.db
cookie.txt
dist/
node_modules/
server.log
server.err
__pycache__/
*.tsbuildinfo
```

## 6. 数据流总览

### 6.1 解析新视频

前端入口：

- 页面：`VideoLibraryPage`
- 函数：`parseVideo(url, delay)`
- 请求：`POST /api/videos/parse`

后端流程：

1. `server.py` 的 `handle_parse_video_api`
2. `extract_bvid` 从 URL 或文本中提取 BV 号
3. `scrape_comments` 抓取视频信息、一级评论、楼中楼回复
4. `save_to_sqlite` 保存视频、用户、评论、图片、表情
5. `scrape_danmaku` 抓取弹幕 XML 和点赞数
6. `save_danmaku_to_sqlite` 保存弹幕
7. 返回解析结果和视频摘要

进度：

- `start_progress("parse", ...)`
- `make_progress_logger("parse", ...)`
- 抓取函数通过 logger 写入日志
- 前端 `useProgressPolling(isParsing, "parse")` 轮询 `/api/progress`

### 6.2 刷新评论

前端入口：

- 页面：`VideoDetailPage`
- 函数：`refreshCommentData(bvid)`
- 请求：`POST /api/refresh?bvid=BV...`

后端流程：

1. `handle_refresh_api`
2. 读取当前视频档案：`load_comment_data`
3. 重新调用 `scrape_comments`
4. `save_to_sqlite(..., replace=True)`
5. 保存前会先将该视频已有评论标记为 `is_deleted = 1`
6. 本次 API 返回的评论再 upsert 回 `is_deleted = 0`
7. 未返回的旧评论保留在数据库中，并显示为“本次未返回”

这个设计用于保留历史评论，不应在刷新时直接删除旧评论。

### 6.3 刷新弹幕

前端入口：

- 页面：`DanmakuPage`
- 函数：`refreshDanmakuData(bvid)`
- 请求：`POST /api/danmaku/refresh?bvid=BV...`

后端流程：

1. `handle_danmaku_refresh_api`
2. 读取当前视频和 `video_raw`
3. 根据 `cid` 抓取 XML
4. 解析弹幕基础字段
5. 批量抓取弹幕点赞数
6. 保存弹幕到 SQLite

重要保护逻辑：

- 如果本次抓到 `0` 条弹幕，但本地此前已有弹幕，则不覆盖旧档案。
- 返回 warning，避免“临时接口空结果”导致本地弹幕被清空。

## 7. 后端 API

### 7.1 `GET /api/health`

用途：健康检查。

返回：

```json
{
  "ok": true,
  "db": "D:\\path\\comments.db"
}
```

### 7.2 `GET /api/videos`

用途：列出本地数据库中所有视频摘要。

返回类型：`VideoListResponse`

关键字段：

- `bvid`
- `title`
- `source_url`
- `owner_name`
- `pic`
- `flat_total_count`
- `active_comment_count`
- `deleted_comment_count`
- `danmaku_count`
- `comment_like_count`

数据来源：`storage.list_video_summaries`

### 7.3 `POST /api/videos/parse`

用途：解析新视频并抓取评论、弹幕。

请求体：

```json
{
  "url": "https://www.bilibili.com/video/BV...",
  "delay": 0.35
}
```

也兼容：

- `video_ref`
- `bvid`

返回类型：`ParseVideoResponse`

可能错误：

- `400`：缺少或无法解析 BV 号
- `409`：已有抓取任务正在进行
- `500`：Bilibili API、网络、解析或保存异常

### 7.4 `GET /api/comments?bvid=BV...`

用途：读取评论详情。

返回类型：`CommentData`

如果不传 `bvid`，读取最近一次抓取的视频。

可能错误：

- `404`：数据库中没有对应视频

### 7.5 `POST /api/refresh?bvid=BV...`

用途：刷新评论。

返回类型：`CommentData`，并额外带 `refresh` 字段。

`refresh` 中的关键字段：

- `before_count`
- `scraped_count`
- `after_count`
- `active_count`
- `deleted_count`
- `added_count`
- `logs`

### 7.6 `GET /api/danmaku?bvid=BV...`

用途：读取弹幕详情和后端时间桶。

可选参数：

- `bvid`
- `limit`

返回类型：`DanmakuData`

如果 `limit` 为空，返回全部弹幕；如果传 `limit=0`，只拿 metadata 和 buckets，不拿 items。

### 7.7 `POST /api/danmaku/refresh?bvid=BV...`

用途：刷新弹幕。

返回类型：`DanmakuData`，并额外带 `refresh` 字段。

`refresh` 中的关键字段：

- `before_count`
- `scraped_count`
- `after_count`
- `warning`
- `logs`

### 7.8 `GET /api/progress`

用途：读取当前抓取进度。

返回类型：`ProgressState`

字段：

- `active`：是否有任务正在运行
- `kind`：`parse` / `comments` / `danmaku`
- `bvid`
- `message`
- `logs`
- `percent`
- `stage`
- `stats`
- `started_at`
- `updated_at`
- `done`
- `error`

前端进度条依赖 `percent`、`stage`、`message`、`stats`、`logs`。

## 8. SQLite 数据模型

Schema 定义在 `bilibili_comments/storage.py` 的 `SCHEMA_SQL`。

### 8.1 `videos`

一行代表一个视频。

关键字段：

- `bvid`：主键
- `aid`
- `title`
- `source_url`
- `fetched_at`
- `pic`
- `video_cid`
- `owner_mid`
- `owner_name`
- `owner_face`
- `stat_view`
- `stat_danmaku`
- `stat_reply`
- `stat_like`
- `pubdate`
- `desc`
- `duration`

注意：

- 弹幕抓取需要 `video_cid`。
- UP 主弹幕识别依赖 `owner_mid` 计算 CRC32 hash。

### 8.2 `users`

评论用户维表。

字段：

- `mid`：主键
- `uname`
- `sex`
- `sign`
- `avatar`
- `level`

### 8.3 `comments`

评论主体表。

字段：

- `rpid`：主键
- `bvid`
- `level`：1 为一级评论，2 为楼中楼回复
- `mid`
- `root`
- `parent`
- `dialog`
- `ctime`
- `time_iso`
- `time_iso_utc`
- `like_count`
- `rcount`
- `reply_count`
- `message`
- `ip_location`
- `first_seen_at`
- `last_seen_at`
- `missing_since`
- `is_deleted`

评论生命周期逻辑：

- 新评论首次保存时设置 `first_seen_at` 和 `last_seen_at`。
- 刷新时先把旧评论标为 `is_deleted = 1`。
- 本次返回的评论 upsert 后恢复为 `is_deleted = 0`，并更新 `last_seen_at`。
- 未返回的评论保留 `is_deleted = 1` 和 `missing_since`。

### 8.4 `comment_pictures`

评论图片表。

字段：

- `rpid`
- `img_src`
- `img_width`
- `img_height`
- `img_size`
- `top_right_icon`
- `play_gif_thumbnail`

### 8.5 `comment_emotes`

评论表情表。

字段：

- `rpid`
- `text`
- `url`
- `jump_title`
- `size`
- `package_id`
- `emote_type`

前端 `CommentText` 会把 message 中匹配到的表情文本替换成图片。

### 8.6 `danmaku`

弹幕表。

字段：

- `dmid`：主键
- `bvid`
- `cid`
- `progress`：视频内出现时间，单位秒
- `mode`：弹幕模式
- `font_size`
- `color`：十进制颜色值
- `ctime`：发送时间 Unix 秒
- `pool`
- `user_hash`：B 站弹幕用户 hash，不展示给用户
- `weight`：弹幕权重
- `like_count`：弹幕点赞数
- `is_up_owner`：是否推断为 UP 主弹幕
- `content`
- `fetched_at`

关于 `weight`：

- 来自弹幕 XML 的第 9 个字段。
- 可理解为 B 站弹幕排序/展示相关权重。
- 用户不一定理解“权重”含义，UI 中如展示，应给出中文解释，避免只写技术字段名。

关于颜色：

- 后端存十进制整数。
- 前端用 `colorNumberToHex` 转成 `#RRGGBB` 作为色块背景。
- 用户不希望看到类似 `FFFF` 的 hash/裸十六进制；UI 应尽量显示“白色、红色、自定义颜色”等可读名称，并用色块直接展示。

关于 UP 主弹幕：

- B 站弹幕 XML 只有 `user_hash`，没有明文 mid。
- 当前逻辑用 `owner_mid` 计算 CRC32，与弹幕 `user_hash` 比对，推断 `is_up_owner`。
- 这是推断，不是由接口直接返回的明文字段。

## 9. Bilibili 抓取实现

### 9.1 评论抓取：`bilibili_comments/scraper.py`

关键函数：

- `extract_bvid`：从 URL 或文本提取 BV 号
- `load_cookie_file`：读取 Netscape cookie 或普通 cookie 字符串
- `make_headers`：构造请求头
- `get_wbi_mixin_key`：从 nav API 获取 WBI 签名 key
- `sign_wbi_params`：生成 WBI 签名参数
- `fetch_video_info`：请求视频信息
- `fetch_main_replies`：分页抓一级评论
- `fetch_child_replies`：分页抓楼中楼
- `normalize_reply`：把 B 站 reply JSON 转成项目统一字段
- `scrape_comments`：评论抓取总入口
- `scrape_to_sqlite`：CLI 使用的抓取并保存入口

评论 API：

- 视频信息：`https://api.bilibili.com/x/web-interface/view`
- WBI nav：`https://api.bilibili.com/x/web-interface/nav`
- 一级评论：`https://api.bilibili.com/x/v2/reply/wbi/main`
- 楼中楼：`https://api.bilibili.com/x/v2/reply/reply`

注意事项：

- B 站评论 API 可能因未登录、cookie 失效、风控、接口变化而返回不完整数据。
- 没有 cookie 时，代码会继续执行，但会记录 warning。
- `delay` 用于降低请求频率，默认 0.35 秒。
- `fetch_main_replies` 会去重，避免 top/hot/admin/upper 等来源重复出现。
- `fetch_child_replies` 同样按 rpid 去重。

### 9.2 弹幕抓取：`bilibili_comments/danmaku.py`

关键函数：

- `extract_cid`：从 `video_raw` 中取 cid
- `fetch_danmaku_xml`：请求 XML 弹幕
- `decode_response_body`：处理 gzip/deflate
- `parse_danmaku_xml`：解析 `<d p="...">content</d>`
- `fetch_danmaku_like_counts`：按 100 个 dmid 一批抓点赞数
- `scrape_danmaku`：弹幕抓取总入口

弹幕 API：

- XML：`https://api.bilibili.com/x/v1/dm/list.so?oid={cid}`
- 点赞数：`https://api.bilibili.com/x/v2/dm/thumbup/stats?oid={cid}&ids=...`

注意事项：

- XML 的 `p` 字段顺序目前按代码解析为：
  1. `progress`
  2. `mode`
  3. `font_size`
  4. `color`
  5. `ctime`
  6. `pool`
  7. `user_hash`
  8. `dmid`
  9. `weight`
- 点赞接口失败时不会让整个弹幕抓取失败，只会把点赞数默认为 0 并记录日志。
- `scrape_danmaku` 默认不走代理，除非传 `use_proxy=True`。

## 10. 前端结构

### 10.1 路由

前端没有使用 React Router，而是在 `App.tsx` 中直接读取 `window.location.pathname`。

路由规则：

- `/`：`VideoLibraryPage`
- `/video/:bvid`：`VideoDetailPage`
- `/danmaku/:bvid`：`DanmakuPage`

页面跳转使用普通 `<a href>` 或 `window.history.pushState` + `PopStateEvent`。

### 10.2 `VideoLibraryPage`

用途：视频库首页。

职责：

- 加载 `/api/videos`
- 搜索本地视频
- 输入新视频 URL/BV 号
- 调用 `/api/videos/parse`
- 显示解析进度
- 展示视频卡片，入口到评论页和弹幕页

关键状态：

- `videos`
- `url`
- `query`
- `isLoading`
- `isParsing`
- `parseDelay`
- `parseProgress`

### 10.3 `VideoDetailPage`

用途：评论详情页。

职责：

- 加载 `/api/comments`
- 刷新评论 `/api/refresh`
- 显示评论统计
- 支持搜索、排序、层级过滤、地区过滤、最低点赞过滤
- 显示时间分布、地区分布、活跃用户、热门评论
- 左/中/右三栏查看评论和详情
- 点击用户头像跳转 B 站用户主页

常见修改点：

- 评论列表行：`CommentRow`
- 评论详情：`CommentDetail`
- 评论文本和表情：`CommentText`
- 评论图片：`CommentImages`
- 时间分布图：`TimeChart`
- 地区分布图：`LocationChart`
- 用户列表：`AuthorList`

布局注意：

- 之前出现过右侧评论详情列遮住中间列的问题。
- 修改三栏布局时重点检查：
  - 容器是否 `min-w-0`
  - grid track 是否过宽
  - 右栏是否有固定宽度和 `overflow` 控制
  - 移动端是否改成单列

### 10.4 `DanmakuPage`

用途：弹幕详情页。

职责：

- 加载 `/api/danmaku`
- 刷新弹幕 `/api/danmaku/refresh`
- 显示弹幕总量、点赞、UP 主弹幕、自定义颜色等指标
- 支持搜索、模式筛选、排序
- 显示时间分布、模式分布、颜色分布、重复弹幕
- 显示弹幕详情和弹幕面板

常见修改点：

- 弹幕列表行：`DanmakuListRow`
- 弹幕详情：`DanmakuDetail`
- 弹幕时间图：`DanmakuTimelineChart`
- 弹幕模式图：`DanmakuModeChart`
- 弹幕颜色：`DanmakuColorList`、`ColorSwatch`
- 重复弹幕：`RepeatedDanmakuList`
- 弹幕面板：`DanmakuPanel`

用户偏好相关：

- 不显示 `user_hash`。
- 颜色要直接显示色块和中文名，不要显示裸 `FFFF` / hash 风格文本。
- 要特别标出 UP 主弹幕。
- 要显示弹幕点赞数。
- 保留颜色分布。

### 10.5 进度条

组件：`ProgressBanner`

Hook：`useProgressPolling(enabled, kind)`

进度来源：

- `/api/progress`
- 后端 `progress_state`

开发注意：

- `progress.percent` 要显示百分比。
- `progress.stage` 要给用户可读阶段。
- `progress.message` 是当前详细说明。
- `progress.stats` 用于显示关键抓取信息。
- `progress.logs` 只展示最近几条，避免把 UI 撑爆。

### 10.6 TypeScript 数据契约

所有前后端 JSON 契约集中在 `src/types.ts`。

如果修改后端返回字段，必须同步更新：

- `src/types.ts`
- `src/App.tsx` 中的渲染逻辑
- 必要时更新 `src/lib/utils.ts`
- 本文档相关章节

不要让前端到处写 `any` 或猜字段。

## 11. UI 与设计约定

当前 UI 风格：

- 安静、信息密集、本地工具感
- 背景：浅灰蓝 `#f4f7fb`
- 主文字：`ink`
- 强调色：Bilibili 粉 `#fb7299`
- 卡片圆角：`rounded-md`
- 图标：lucide-react

开发原则：

- 不做营销落地页，首屏就是可用工具。
- 控件优先使用图标 + 简短文本。
- 列表、表格、图表要支持窄屏和宽屏。
- 文本不能遮挡、溢出或盖住其它列。
- 对三栏布局要特别小心，必须使用 `min-w-0` 和合理的 grid track。
- 评论、弹幕这种长文本要 `break-words`、`line-clamp` 或 `overflow-y-auto`。
- 不要显示用户明确不想看的技术字段，例如弹幕 `user_hash`。

## 12. 已知问题与风险

### 12.1 `server.py` 中的中文字符串可能存在编码异常

当前 `server.py` 中部分中文提示在终端读取时显示为乱码，例如进度阶段和错误文案。可能原因：

- 文件内容曾被错误编码保存。
- 或 PowerShell 输出编码导致显示异常。

影响：

- API 返回的进度文案可能对用户不可读。
- `progress_stage` 和 `progress_stats` 中也有乱码 key，UI 可能显示不理想。

如果要修复：

1. 单独开分支，例如 `fix/progress-text-encoding`
2. 将后端中文字符串统一改成 UTF-8 可读中文
3. 同步检查前端显示
4. 执行 `pnpm build` 和 Python 编译检查

### 12.2 Bilibili API 不稳定

可能出现：

- HTTP 404
- API code 非 0
- 未登录只返回部分评论
- 弹幕 XML 暂时返回空
- 点赞接口失败
- WBI 签名规则变化

开发时不要假设 API 永远稳定。UI 应清楚显示错误或 warning。

### 12.3 弹幕空结果保护

用户曾遇到“抓取弹幕一直是 0，过一会刷新又有”的情况。

因此 `handle_danmaku_refresh_api` 已经有保护逻辑：

- 本次抓取 `0`
- 本地旧弹幕数量 `> 0`
- 不覆盖本地旧弹幕

后续修改弹幕保存逻辑时不要移除这个保护。

### 12.4 评论刷新不是删除同步

评论刷新时，“本次未返回”不一定等于用户主动删除，也可能是接口分页、风控、折叠、cookie 权限等原因。

UI 文案应使用“本次未返回”而不是绝对的“已删除”。

### 12.5 单文件前端较大

`src/App.tsx` 是薄路由入口；页面和组件已经按领域拆分。

后续继续重构时要谨慎：

- 不要在功能修复时顺手大规模拆文件。
- 如果要拆，应单独开重构分支。
- 拆分前先保证现有行为有构建验证。
- 现有前端边界：
  - `src/pages/*` 放页面状态和页面布局。
  - `src/components/comments/*` 放评论领域展示。
  - `src/components/danmaku/*` 放弹幕领域展示和弹幕工具。
  - `src/components/common.tsx` 放跨页面通用组件。
  - `src/api/client.ts` 放前端请求封装。
  - `src/hooks/*` 放 React hooks。

## 13. 常见开发任务定位

### 13.1 修改评论抓取

优先看：

- `bilibili_comments/scraper.py`
- `bilibili_comments/storage.py`
- `server.py` 的 `handle_parse_video_api` 和 `handle_refresh_api`

需要同步：

- SQLite schema
- `load_comment_data`
- `src/types.ts`
- 评论页 UI

### 13.2 修改弹幕抓取

优先看：

- `bilibili_comments/danmaku.py`
- `bilibili_comments/storage.py` 的 `save_danmaku_to_sqlite` 和 `load_danmaku_data`
- `server.py` 的 `handle_danmaku_refresh_api`

需要同步：

- `DanmakuItem`
- `DanmakuData`
- `DanmakuPage`
- 颜色、点赞、UP 主标记相关 UI

### 13.3 修改数据库字段

优先看：

- `SCHEMA_SQL`
- `ensure_schema`
- `ensure_*_column`
- `save_*_to_sqlite`
- `load_*_data`

要求：

- 兼容已有 `comments.db`
- 用 `ALTER TABLE ADD COLUMN` 做轻量迁移
- 不要要求用户手动删数据库
- 不要破坏旧数据

### 13.4 修改进度显示

优先看：

- `server.py`
  - `progress_state`
  - `start_progress`
  - `update_progress`
  - `finish_progress`
  - `fail_progress`
  - `progress_stage`
  - `progress_percent`
  - `progress_stats`
- `src/App.tsx`
  - `useProgressPolling`
  - `ProgressBanner`

### 13.5 修改评论详情布局

优先看：

- `VideoDetailPage`
- `CommentRow`
- `CommentDetail`
- `TimeChart`
- `LocationChart`
- `AuthorList`

重点检查：

- 三栏 grid 宽度
- 右栏 sticky/overflow
- 中间列表最小宽度
- 评论长文本换行
- 图片尺寸
- 移动端单列表现

### 13.6 修改弹幕颜色显示

优先看：

- `colorNumberToHex`
- `colorNameForDanmaku`
- `ColorSwatch`
- `DanmakuColorList`
- `DanmakuDetail`

要求：

- 色块必须保留。
- 中文名必须清楚。
- 不要显示裸 hash 或难懂十六进制。

## 14. 验证清单

### 14.1 每次代码改动后

```powershell
pnpm build
python -B -m py_compile server.py fetch_bilibili_comments.py bilibili_comments\storage.py bilibili_comments\danmaku.py bilibili_comments\scraper.py bilibili_comments\url_utils.py bilibili_comments\__init__.py
git status --short --ignored
```

### 14.2 前端 UI 改动后

至少检查：

- `/`
- `/video/<已有 BV>`
- `/danmaku/<已有 BV>`

重点看：

- 页面是否空白
- 三栏是否互相遮挡
- 按钮文字是否溢出
- 进度条是否显示百分比和阶段
- 评论详情是否出现
- 弹幕列表是否显示点赞、UP 主标记、颜色
- 时间分布和颜色分布是否非空

### 14.3 抓取逻辑改动后

至少检查：

- 新视频解析
- 评论刷新
- 弹幕刷新
- `/api/progress`
- 本地数据库是否保留历史未返回评论
- 弹幕 0 条保护是否仍生效

### 14.4 提交前

```powershell
git diff --stat
git status --short --ignored
```

确认：

- 没有 `cookie.txt`
- 没有 `comments*.db`
- 没有 `dist/`
- 没有 `node_modules/`
- 没有日志和缓存
- 没有不相关格式化或重构

## 15. 发布与推送流程

普通需求分支：

```powershell
git status --short --branch
git switch main
git pull --ff-only
git switch -c <branch-name>
# edit
pnpm build
python -B -m py_compile server.py fetch_bilibili_comments.py bilibili_comments\storage.py bilibili_comments\danmaku.py bilibili_comments\scraper.py bilibili_comments\url_utils.py bilibili_comments\__init__.py
git status --short --ignored
git add <files>
git commit -m "<message>"
git push -u origin <branch-name>
```

用户确认后合并：

```powershell
git switch main
git merge --ff-only <branch-name>
git push origin main
```

如果 GitHub 凭据助手在无交互环境里失败，可使用已登录的 GitHub CLI token 临时推送，但不要把 token 写入配置或文档：

```powershell
$token = & 'C:\Program Files\GitHub CLI\gh.exe' auth token
$remote = 'https://x-access-token:' + $token + '@github.com/sanxiadaba/bilibili-comment-danmaku-tool.git'
git -c credential.helper= -c credential.https://github.com.helper= -c credential.https://github.com.username= push $remote <branch>
```

执行后检查 `.git/config`，确保没有 token 残留。

## 16. README 与本文档的分工

- `README.md`：面向使用者，说明项目用途、安装、启动、cookie 和本地数据。
- `AGENTS.md`：面向开发 agent，说明架构、数据流、接口、数据库、开发规则和风险。

当项目行为改变时，两个文档都可能需要更新：

- 用户可见行为改变：更新 `README.md`
- 开发方式、接口、schema、架构改变：更新 `AGENTS.md`
