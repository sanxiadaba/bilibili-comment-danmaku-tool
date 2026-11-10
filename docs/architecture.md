# 代码结构

这份文档只回答一个问题：**想改某处，该看哪个文件**。

## 一、一次请求怎么走

以「打开评论页」为例：

```text
浏览器 /video/BVxxx?db_id=db:xxx
  └─ App.tsx 按路径选页面        frontend/src/App.tsx
      └─ VideoDetailPage          frontend/src/pages/VideoDetailPage.tsx
          └─ fetchCommentData()   frontend/src/api/client.ts   GET /api/comments?bvid=…&db_id=…
              └─ server.py do_GET → handle_comments_api
                  └─ load_comment_data()   backend/bilibili_comment_danmaku/storage.py
                      └─ SQLite 文件 data/databases/<UP主>/<BVID>.db
```

按钮触发的写操作走 `do_POST`，同样先过 `check_mutating_request`（只接受本机页面、带防护头的请求），再进入对应 `handle_*_api`。

## 二、目录与职责

| 位置 | 职责 | 从哪读起 |
| --- | --- | --- |
| `backend/server.py` | HTTP 服务、路由、接口编排、启动入口 | `do_GET` / `do_POST` → `handle_*_api` |
| `backend/bilibili_comment_danmaku/storage.py` | 所有 SQLite 读写、schema 迁移、分页、删除 | `ensure_schema` → `save_comments_to_sqlite` → `load_comment_data` |
| `backend/bilibili_comment_danmaku/scraper.py` | 评论/楼中楼抓取、WBI 签名、限流退避 | `scrape_comments` → `fetch_main_replies` / `fetch_child_replies` |
| `backend/bilibili_comment_danmaku/danmaku.py` | 弹幕 XML 抓取、点赞数批量查询 | `scrape_danmaku` |
| `backend/space_archive.py` | UP 主视频列表 + 批量归档任务 | `fetch_space_videos`、`SpaceArchiveService` |
| `backend/video_tasks.py` | 单视频解析任务 | `VideoParseTaskService` |
| `backend/archive_delete_tasks.py` | 删除任务 | `ArchiveDeleteTaskService` |
| `backend/task_queue.py` | 三种任务共用的队列、暂停/恢复/停止、落盘 | `TaskQueue` |
| `backend/database_registry.py` | 数据库目录扫描、聚合列表、导入导出路径 | `iter_catalog_database_paths`、`list_all_video_summaries_page` |
| `backend/app_cli.py` | 命令行入口 | `build_parser` |
| `backend/desktop_entry.py` | exe 入口（起服务 + 浏览器） | `main` |
| `frontend/src/pages/*` | 三个页面 | `VideoLibraryPage` → `VideoDetailPage` → `DanmakuPage` |
| `frontend/src/api/client.ts` | 全部 HTTP 封装 | 一个接口一个函数 |
| `frontend/src/components/*` | 页面拆出来的组件 | 按目录名对应功能 |

## 三、数据模型

一个视频一个库文件，库内是四张主表：

```text
videos     一个视频一行（标题、UP、统计、抓取时间）
comments   评论和楼中楼，level=1 主楼 / level=2 回复；is_deleted 表示"本次刷新没返回"
users      评论作者
danmaku    弹幕
archive_meta  导出库的清单信息
```

`main` 不是文件，是「遍历 `data/databases/**` 后合并出来」的视图；所以聚合视图能看、能导出，但不能直接删（没有唯一文件可删），删除会要求先选具体库。

schema 用 `PRAGMA user_version` 标记版本：`ensure_schema_if_needed` 只在文件版本落后时迁移一次，读请求不做迁移。

## 四、抓取层

- 所有 B 站请求都限速：全局最小间隔 + 随机抖动，遇到 412/429 进入指数冷却；冷却等待可被停止请求打断。
- WBI 签名密钥有内存缓存和本地持久化，失败会退回系统 opener。
- 评论分页按 cursor 走；楼中楼按根评论并发抓（4 线程），单条失败只记日志，不丢整轮。
- 匿名请求只返回极少量评论，这是接口行为；登录态走 `auth_store.CookieStore`。

## 五、长任务

UP 主归档、单视频解析、删除都进 `TaskQueue`：状态存在任务对象里并落盘，服务重启后能恢复排队；`control_tasks` 统一处理 pause / resume / stop / retry / clear。

评论刷新和弹幕刷新**不进队列**，是同步请求，靠 `progress_state` 的停止标志在下一个分页退出。原因：它们只操作单个视频，逻辑简单，入队反而要维护两套状态机。

## 六、前端

- `App.tsx` 只看路径：`/` 视频库、`/video/<BV>` 评论页、`/danmaku/<BV>` 弹幕页。
- 页面里所有请求都带 `AbortController` 或单调请求序号，慢响应不能覆盖新状态。
- 大列表用 `VirtualList`（窗口切片 + 每一行固定估算高度），不要一次渲染全量。
- 进度轮询只有一个 `useProgressPolling` 实例，后台标签页自动降频。

## 七、改哪里

| 想改 | 看 |
| --- | --- |
| 新增一个接口 | `server.py` 的 `do_GET`/`do_POST` + 对应 `handle_*_api`；前端加 `api/client.ts` 函数 |
| 抓取字段/翻页 | `scraper.py` 的 `normalize_reply`、`fetch_main_replies` |
| 弹幕采集 | `danmaku.py` 的 `parse_danmaku_xml`、`scrape_danmaku` |
| 表结构 | `storage.py` 的 `SCHEMA_SQL` + `ensure_schema`，记得升 `SCHEMA_VERSION` |
| 分页/排序/筛选 | `storage.py` 的 `select_comment_rows`、`list_video_summaries_page` |
| 删除逻辑 | `storage.py` 的 `delete_*`、`archive_delete_tasks.py` |
| UP 主批量归档 | `space_archive.py` |
| 界面布局 | `frontend/src/pages/*` 和 `components/*` |
| 样式 | `frontend/src/styles.css` + Tailwind 类 |

## 八、测试地图

| 测试 | 守住什么 |
| --- | --- |
| `tests/backend/test_storage_archive.py` | 存储、分页、删除、导出 |
| `test_scraper_flows.py` / `test_scraper_guards.py` | 抓取流程、退避、部分失败 |
| `test_task_queue` 相关 | 队列状态、暂停/恢复/停止、落盘恢复 |
| `test_http_hardening.py` | Host / Origin / 路径穿越 / 静态缓存 |
| `test_data_integrity_guards.py` | 缩水保护、变量上限、迁移只跑一次 |
| `tests/frontend/*` | API 封装、轮询、虚拟列表、组件行为 |

跑法：`pnpm test`（编码检查 + 后端 unittest + 前端 Vitest）。
