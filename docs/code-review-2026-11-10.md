# 代码评审报告（2026-11-10）

评审对象：`main` @ `da883bf`（Merge branch 'codex/fix-task-label-and-login-backoff'）

结论摘要：**仓库可构建、可运行、可联网抓取，基础工程质量良好**（后端 149 个 unittest 全通过、前端 56 个 Vitest 全通过、`pnpm build` 一次通过、匿名真实抓取成功）。但存在 **3 条会静默做错事的数据正确性缺陷**，其中 1 条已实测复现：聚合视图下删除视频会报"成功"而数据未删除。

缺陷统计：P0 3 条、P1 7 条、P2 21 条。

---

## 一、可运行性验证（实测）

验证环境：Windows、Python 3.14.4、Node v22.22.1、pnpm 11.28.5。仓库初始状态无 `node_modules`、无 `data/`、无 `dist/`。

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| 后端依赖 | 检查全部 import | **零第三方依赖**（纯标准库），无 `requirements.txt`/`pyproject.toml` |
| 后端测试 | `python -B -m unittest discover -s tests/backend -p "test_*.py"` | 149 tests, OK, 16s |
| 前端依赖 | `pnpm install --frozen-lockfile` | 191 packages, OK |
| 前端测试 | `vitest run --config frontend/vite.config.ts` | 9 files / 56 tests, OK |
| 类型检查 | `tsc -p frontend/tsconfig.json --noEmit` | 0 error |
| 构建 | `vite build --config frontend/vite.config.ts` | OK，JS 372.85 kB（gzip 110.93 kB） |
| 全链路 | `pnpm build` | 编码检查 + 后端 + 前端 + tsc + 打包，一次通过 |
| 服务启动 | `python backend/server.py --host 127.0.0.1 --port 18001` | 成功，端口递增逻辑生效 |
| API | `GET /api/databases`、`GET /api/videos` | 200，返回合法 JSON |
| 静态页 | `GET /`（构建后） | 200，返回 SPA 入口 |
| 防护头 | `POST` 带非本机 `Origin`、无 `X-Bilibili-Tool-Request` | 403（符合设计） |
| 真实抓取 | `python backend/app_cli.py fetch-video BV1xx411c7mD --comment-pages 1 --skip-children` | 成功：WBI 签名、评论 3 条、弹幕 3600 条，落库到 `data/databases/<UP>/<BVID>.db` |

> 结论：**能正常运行。** 没有发现构建断裂、依赖缺失或 API 契约失效。

## 二、使用方法

### 安装与运行

```powershell
pnpm install
pnpm build          # 产出 dist/，后端依赖它提供页面
pnpm server         # http://127.0.0.1:8001/，被占用时自动递增端口
```

### 开发模式

```powershell
pnpm server         # 终端 1：后端
pnpm dev            # 终端 2：Vite 开发服务器（/api 代理到 8001）
```

注意：`frontend/vite.config.ts:14` 把代理地址硬编码为 `http://127.0.0.1:8001`，而服务端端口会自动递增。**8001 被占用时开发模式失效**（见 P1-7）。

### CLI

```powershell
python backend/app_cli.py fetch-video BV1xx411c7mD
python backend/app_cli.py list-space https://space.bilibili.com/1538787344 --max-videos 3
python backend/app_cli.py archive-space https://space.bilibili.com/1538787344 --max-videos 1
```

打包后的 exe 同样支持 CLI：`app.exe cli fetch-video <BV>`（打包脚本会改写成 `--cli`）。

### Windows 打包

```powershell
pnpm package:windows
```

产物在 `release/`，根目录只留一个可见 exe，依赖在 `_internal/`，数据在 `data/`、日志在 `logs/`。

### 数据位置

- 一视频一库：`data/databases/<UP主>/<BVID>.db`
- 遗留主库：`data/comment_danmaku.db`（页面里的 `main` 是聚合视图 id，不要求这个物理库存在；但当前启动仍会创建它，见 P2-16）
- Cookie（可选）：`data/cookie.txt`；缺失时按匿名运行

---

## 三、缺陷清单

严重度定义：**P0** = 会静默产生错误数据或破坏数据；**P1** = 核心功能在真实数据规模下失效；**P2** = 健壮性、性能、可维护性问题。

### P0（3 条）

#### P0-1 聚合视图下的删除/导出作用在遗留主库，报成功但没操作真实数据

- 位置：`backend/server.py:890`（导出）、`backend/server.py:1035`（删除）、`backend/database_registry.py:25-26`（`main` → `DEFAULT_DB`）
- 证据：**已实测复现**
  - `POST /api/archive/delete {"bvid":"BV1xx411c7mD"}`（不带 `db_id`）返回 `202 {"ok":true,"deleted_videos":1,"message":"删除任务已加入队列"}`
  - 事后核查：`data/databases/碧诗_2/BV1xx411c7mD.db` 中该视频与 3 条评论**依然存在**；`data/comment_danmaku.db` 为空库
- 影响：新装用户（遗留库为空）→ 静默空操作并报成功；有旧数据的用户 → **操作到错误的归档上**，可能删除/导出用户没有选中的数据
- 修法：`db_id` 为 `main`/缺省且给了 `owner_mid`/`bvids` 时，按 `find_video_database_path` 逐库解析——导出合并成一个归档；删除返回 400 并说明需要选定具体库，前端删除时始终传 `video.db_id`
- 验收：聚合视图导出 UP 产出非空归档；聚合视图删除返回 400 且信息明确；新增 3 个回归测试（导出扇出、400 拒绝、前端传参）

#### P0-2 "重试"会覆盖任务的目标库与全部归档参数

- 位置：`backend/server.py:850-853`（`retry_defaults` 恒含 `db_path`）、`backend/task_queue.py:171-181`（`fields.update(defaults)` 直接盖写）
- 证据：代码确认。`retry_defaults = {"db_path": str(self.resolve_db_path_from_body(body)), ...}`，而 `resolve_db_path_from_body` 默认返回遗留主库；`retry_fields` 先收集任务原字段，再无条件 `update` 默认值
- 影响：（a）删除任务重试 → 目标库变成遗留空库；（b）`max_videos=5` 的 UP 任务重试 → 变成"归档整个 UP"，丢 `no_cache`，可能跑几小时/几 GB
- 修法：`retry_fields` 只填补缺失键（`setdefault` 语义），`retry_defaults` 移除 `db_path`/`options`；只有调用方显式传了 `db_id` 才下发库路径
- 验收：构造带 `db_path` + `options={max_videos:5,no_cache:true}` 的失败任务，重试后两字段逐项一致

#### P0-3 评论数超过 32766 的视频永远无法保存

- 位置：`backend/bilibili_comment_danmaku/storage.py:436-439`
- 证据：子代理实测——5 万条评论调用 `save_comments_to_sqlite` 抛 `sqlite3.OperationalError: too many SQL variables`；SQLite 该上限为 32766（`conn.getlimit(SQLITE_LIMIT_VARIABLE_NUMBER)`）
- 影响：事务回滚不会损坏数据，但**整轮抓取（可能数小时）全部白费且重试必然再失败**；热门视频普遍超过 3 万条
- 修法：改用临时表（`CREATE TEMP TABLE scraped(rpid TEXT PRIMARY KEY)` + 批量 `executemany` + `DELETE ... WHERE rpid IN (SELECT rpid FROM scraped)`），或把 rpid 按 5000 一批分块
- 验收：4 万条评论保存成功；新增回归测试；现有 149 个测试保持全绿

### P1（7 条）

#### P1-1 聚合视频列表每库静默截断在 200 条

- `backend/database_registry.py:120-125` 传 `limit=100000`，`backend/bilibili_comment_danmaku/storage.py:752` 把 limit 夹到 200
- 证据：实测 201 条视频的库返回 `total=200`，`offset=200` 返回 0 行但 `has_more=true`
- 影响：导入的大库/合集库后半部分视频在 UI 里不可见、翻页也到不了
- 修法：为内部聚合提供不设上限的 limit，或改为在目录查询里分页；200 的上限只保留给单库公开 API

#### P1-2 评论刷新没有空结果/部分结果保护

- `backend/server.py:1277-1285` 无条件 `save_comments_to_sqlite(..., replace=True)`；`storage.py:276-285` 先把该视频所有评论置 `is_deleted=1`，只把本轮返回的行改回来
- 影响：远端返回 0 条或提前 `is_end`（软封锁、API 变更、匿名限流）→ 历史评论被整批标记删除，`comment_total_count` 被小数字覆盖。弹幕路径已有等价保护（`server.py:1376-1387` 等），评论没有
- 修法：`scraped_count == 0 && before_count > 0`（或低于已有的一半）时跳过保存并返回警告；`save_comments_to_sqlite` 在入参为空时不得把 `comment_total_count` 写成 0

#### P1-3 评论/弹幕刷新是同步、不可取消、无页数上限的长任务

- `backend/server.py:1244-1334`、`1336-1437`：整轮抓取跑在 HTTP 请求线程上并持有全局 `refresh_lock`，无暂停/停止标志、无页数上限
- 影响：50 万评论 ≈ 2.5 万页 × 0.85s 请求下限 ≈ 6 小时以上，期间所有队列被阻塞，浏览器请求无法取消。这违反项目硬规则"长任务必须能暂停、停止、恢复"——目前只有 UP 归档/解析/删除三种任务进了队列
- 修法：把刷新作为任务类型入队并复用 `VideoParseTaskService` 的取消逻辑；强制 `delay <= 5` 与页数上限；至少在 `progress_state` 加停止标志并让进度回调检查

#### P1-4 刷新响应把整个归档序列化进内存与 HTTP 响应

- `backend/server.py:1261`（先全量载入）、`1286-1294`（再全量载入并放进 POST 响应）、`1391`（弹幕 `limit=None`）
- 证据：`load_comment_data(limit=None)` 在 2 万评论上 = 0.79s / 22.2MB JSON（约 1.1KB/条，`comments` 与 `comment_items` 内容重复）；10 万评论 ≈ 110MB
- 修法：刷新后只返回首页数据 + 汇总信息，全量需要显式 `full=1`；`before_count` 用聚合查询而非全量加载

#### P1-5 视频库搜索与 UP 主筛选只覆盖已加载的 40 条，且筛选时隐藏翻页

- 位置：`frontend/src/components/video-library/VideoListPanel.tsx:63`（`hasMore && !query && !selectedOwnerName`）、`frontend/src/pages/VideoLibraryPage.tsx:219`、`frontend/src/lib/videoLibrary.ts:112-123`、`frontend/src/api/client.ts:101-108`
- 证据：已核对源码。`fetchVideos` 每页 40 条，`filterVideos` 只在内存切片上过滤，一旦输入关键词或选中 UP 主，"加载更多"按钮直接消失
- 影响：500 条视频的库里搜索第 3 页的标题 → 显示"暂无匹配的视频"，且无法翻页自救；点某个 UP 主 → 只显示已加载的那部分（通常是 0 行），而侧栏显示的是全量计数
- 修法：把 `q` 与 `owner_mid` 下推给 `/api/videos`；或最小改动——筛选时保留翻页并提示"已加载 N / 总数 M"

#### P1-6 前端埋点请求 100% 被 403 丢弃

- 位置：`frontend/src/api/client.ts:230-249`（`sendBeacon` 无法设置自定义头；兜底 `fetch` 也没设）、`backend/server.py:426-447`（所有 POST 统一走防护校验）
- 证据：**已实测**——`POST /api/logs/client` 带同源 `Origin`、无 `X-Bilibili-Tool-Request` → 403；带上该头 → 200
- 影响：约 40 个埋点事件全部丢失；且 `requestJson` 每次调用发 2 条日志 POST，等于**每个 API 调用额外产生 2 个必然 403 的请求**，日志里持续刷错误
- 修法：统一走一个带防护头的 `fetch(..., {keepalive:true})` 助手，`sendBeacon` 只作为 `pagehide` 兜底；或让 `/api/logs/client` 免于防护校验（它是纯写入的遥测）

#### P1-7 开发模式代理端口与服务端端口递增逻辑冲突

- 位置：`frontend/vite.config.ts:14`（硬编码 `http://127.0.0.1:8001`）、`backend/local_server.py:9-17`（端口从 8001 递增）
- 影响：8001 被占用时后端起在 8002，而 `pnpm dev` 的 `/api` 仍指向 8001 → 开发模式整页 API 失败，且报错信息是"后端返回了非 JSON 响应"，极难定位
- 修法：让启动脚本把实际端口写入环境变量/临时文件，Vite 配置读取它；或探测 8001 起连续端口

### P2（21 条，按主题归组）

#### 存储与数据一致性

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| P2-1 | `storage.py:428-472` | 评论有 `mid` 但响应缺 `member` 对象时触发 `IntegrityError: FOREIGN KEY constraint failed`，整批保存失败（已实测） | 为每个引用到的 mid 预插占位 `users` 行，或校验时跳过畸形节点 |
| P2-2 | `storage.py:565-566, 683-685, 177-194` | 每个 GET 都跑一遍 `ensure_schema`（切 WAL、5×`table_info`、迁移 UPDATE、全表 `backfill_comment_lifecycle`），2 万评论实测 4.8ms/次，且拿写锁 | 用 `user_version` 只在启动时迁移一次；GET 用只读连接 |
| P2-3 | `storage.py:701-702, 1289-1335` | 每取 500 条评论都要载入该视频**全部**图片/表情（实测 12.9ms+12.9ms） | 按本页 rpid 范围过滤，或详情页懒加载 |
| P2-4 | `storage.py:1085, 1145, 1002-1022` | 运行时切换 journal_mode（DELETE↔WAL）与并发 GET 的 WAL 设置互相竞争，可能出现 `database is locked`（busy_timeout 最长 60s） | 运行期不再切换模式；维护操作与读操作统一串行化 |
| P2-5 | `storage.py:1382-1404, 717-734` | 评论分页按扁平行（1 级+2 级混排），楼中楼可能孤儿化；实测 1 主楼+2 回复、`limit=1` 时第 1 页 `comments=[]` 但 `has_more=true` | 按主楼分页，回复用 `root IN (本页主楼)` 取；或只返回 `comment_items` 由前端建树 |
| P2-6 | `archive_delete_tasks.py:46-80, 159-177` | 删除任务完全忽略 pause，stop 只在取锁前检查；分段提交（`storage.py:1098/1113/1125`）失败会留下"评论删了、videos 行还在"的半成品 | 在进度回调里检查 pause/stop；删除前先标记或先删 `videos` 行，保证单事务 |

#### 网络抓取

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| P2-7 | `space_archive.py:42-49, 87` | UP 视频列表缓存**永不过期**，`cached_at` 写了从不读，UI 也不传 `no_cache` → 首次归档后该 UP 新视频永远进不来；缓存文件损坏时 `json.loads` 裸读直接崩任务 | 加 TTL 或每次都探第 1 页比对总数；读取包 try/except；UI 暴露 `no_cache` |
| P2-8 | `scraper.py:1044-1101, 1181-1225` | 楼中楼翻页只以"空页/达到 api_count"退出，接口重复返回同一页时会**死循环**并一直持有全局锁；子回复失败会丢弃所有已抓数据并等待所有 worker | 增加"无增长页数上限"守卫；失败时保存部分结果或 `cancel_futures=True` 并标记 partial |
| P2-9 | `server.py:1369-1373`、`video_tasks.py:189-193` | 弹幕刷新与单视频解析请求弹幕时**不带 Cookie/headers**（只有 `space_archive.py:507-514` 是对的） | 统一 `scraper.make_headers(bvid, cookie)` |
| P2-10 | `danmaku.py:195-199, 220-236`、`storage.py:518-519` | 点赞数接口失败时静默写入 `like_count=0`，配合 `replace=True` 抹掉历史点赞数 | 查询失败时保留旧值，或跳过本次弹幕写入 |
| P2-11 | `space_archive.py:265-276` | `is_complete` 只要非零就算完成，抓到 20/10000 条也永不重试 | 与期望数量比对（带容差），或落一个 `partial` 标记 |

#### HTTP 与安全

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| P2-12 | `http_utils.py:57-64` | 静态路径用字符串前缀校验（`str.startswith`），同级目录名以 `dist` 开头即可被读取；且未知路径一律 200 返回 `index.html`（实测 `/package.json` → 200） | 改用 `Path.relative_to`/`is_relative_to`；缺失文件返回 404；SPA 回退只用于导航路由 |
| P2-13 | `server.py:426-447, 303-342, 1443` | 防护校验只覆盖 POST；GET 路由完全不校验 `Host`；`--host` 无校验，绑到局域网即等于远程可写；该头是 CSRF 缓解而非鉴权 | 非 loopback `--host` 默认拒绝；所有路由校验 `Host`；写操作引入每次启动的随机 token |
| P2-14 | `http_utils.py:16-19, 113-122`、`server.py:1121-1135` | 无 socket/请求超时，`rfile.read(length)` 在短包时永久阻塞；512MB 上传整体读入内存，multipart 再复制一遍（峰值 >1GB） | 设置 handler `timeout`；限制上传大小或流式落盘 |
| P2-15 | `server.py:419-421, 600-615, 505-522` | 未捕获异常直接断 TCP 连接（二维码轮询网络错误、列库 OSError），前端看到的是"后端返回了非 JSON 响应" | `do_GET`/`do_POST` 兜底返回 JSON 500，上游错误映射 502 |

#### 日志与凭据

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| P2-16 | `auth_store.py:68-86` | "清除 Cookie"在 unlink 前先备份明文到 `data/backups/cookie/cookie-*.txt`，且备份永不清理 | 显式清除不备份；备份目录加数量/时限清理 |
| P2-17 | `app_logging.py:272-294` | 脱敏只看字段名是否含 cookie/token/password 等，**消息正文与异常栈不脱敏**，`log_event("x", f"SESSDATA={v}")` 会原样落盘 | 对 message 与 exception 文本做正则脱敏（`SESSDATA=...`、`bili_jct=...`、`DedeUserID__ckMd5=...`） |
| P2-18 | `auth_store.py:136` | 二维码轮询把 B 站返回的 `data.url` 原样作为 `login_url` 下发（成功时可能含登录凭据） | 去掉 query/fragment，或成功后不下发 |

#### 打包与路径

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| P2-19 | `wbi.py:87-91`、`scraper.py:123-127`、`space_archive.py:26` | WBI 密钥缓存/退避状态路径基于包目录或 CWD，不是注入的数据根；冻结打包后会落到 `_internal/data` 或进程 CWD，且写入失败被静默吞掉 → 重启后可能重新高频请求 B 站 | 统一走一个注入的 app-data 根（与 `database_dir`/`log_dir` 同源） |
| P2-20 | `database_registry.py:47-65, 80-89` | 归档目录按**可变的 UP 主名**分组：改名就会为同一视频生成第二份 DB；`find_video_database_path` 取 mtime 最新，与聚合列表"取最丰富"的口径不一致 | 目录键改为 mid（需迁移），或改名时移动合并 |
| P2-21 | `database_registry.py:583-585, 665-679` | Windows 保留设备名（`CON`/`NUL`/`COM1`…）未过滤，UP 主名恰好命中时 `mkdir`/写文件失败；长 UP 名 + BVID 逼近 MAX_PATH | 加保留名转义与长度上限 |

### 其他值得记录的小问题

- `scripts/start_server_8000.ps1` 是遗留 shim，与"不要写回 8000"的硬规则矛盾，建议删除
- `data/comment_danmaku.db` 在启动时仍被创建（`desktop_entry.py:99`），但不进 catalog、不进聚合列表、也无迁移路径 → 老用户升级后看到空库（同上 P2 主题，建议做一次性迁移）
- 前端测试全部是 `renderToStaticMarkup`（node 环境，无 jsdom）：effects、清理、abort/竞态、`VirtualList`、三个 page（合计约 88KB 最富状态的代码）**零覆盖**
- `app_logging` 的 `log_message` 仍向 stdout 打印，打包为无控制台应用时 `sys.stdout` 可能为 `None`，`safe_print` 只捕获 `OSError`（`http_utils.py:164-168`）
- 无 CI 测试 workflow：`.github/workflows/` 只有 `release.yml`，PR 阶段零检查，测试只在打 Windows 包时才跑

---

## 四、明确排除项（评审判定"没有问题"）

避免后续重复排查，以下项已确认：

- **无 SQL 注入**：全部值都走参数化；f-string 只用于内部占位符数量
- **无 zip/tar 处理**，因此不存在 zip-slip 面
- **无越界文件读写**：写操作限定在 `data/`、导出目录、日志目录内（静态路径的那处前缀缺陷只影响同级 `dist*` 目录）
- `VirtualList` 确实做了虚拟化（窗口切片 + `translateY` + `ResizeObserver`），问题在 O(n) 重算与空列表首渲染，不在"假虚拟化"
- 所有列表都有 key；CSV 导出带 UTF-8 BOM；源码为 UTF-8 无 BOM

## 五、实测复现命令

```powershell
# 环境
python --version            # 3.14.4
node --version              # v22.22.1

# 测试与构建
python -B -m unittest discover -s tests/backend -p "test_*.py"
pnpm install --frozen-lockfile
pnpm build

# P0-1 复现：聚合视图删除报成功但数据未删
python backend/app_cli.py fetch-video BV1xx411c7mD --comment-pages 1 --skip-children
# 起服务后：POST /api/archive/delete  {"bvid":"BV1xx411c7mD"}（不带 db_id）
# 返回 202 deleted_videos=1，但 data/databases/<UP>/BV1xx411c7mD.db 仍在

# P1-6 复现：埋点被 403
# POST /api/logs/client  带 Origin、不带 X-Bilibili-Tool-Request  → 403
# POST /api/logs/client  带 Origin、带 X-Bilibili-Tool-Request    → 200
```

## 六、建议排期

1. **止血（P0）**：P0-1 → P0-2 → P0-3，一分支一条，各自补回归测试
2. **数据完整性保护**：P1-2（评论空结果保护阀）、P2-6（删除任务可暂停/原子化）
3. **可用性**：P1-5（搜索下推）、P1-1（200 条截断）、P1-7（开发端口）、P1-6（埋点）
4. **性能**：P1-4（刷新响应瘦身）、P2-3（分页只取本页图片表情）、P2-2（迁移只跑一次）、聚合列表走目录索引
5. **安全加固**：P2-13、P2-12、P2-16、P2-17
6. **工程化**：补 CI 测试 workflow、前端引入 jsdom + testing-library、拆分 `server.py`/`storage.py`/`scraper.py`

## 七、规模参考

| 模块 | 行数 |
| --- | --- |
| `backend/server.py` | 1507 |
| `backend/bilibili_comment_danmaku/storage.py` | 1501 |
| `backend/bilibili_comment_danmaku/scraper.py` | 1351 |
| `backend/space_archive.py` | 816 |
| `backend/database_registry.py` | 679 |
| `frontend/src/pages/VideoLibraryPage.tsx` | 38967 B |
| `frontend/src/pages/VideoDetailPage.tsx` | 27099 B |
| `frontend/src/pages/DanmakuPage.tsx` | 21655 B |

性能实测（本机）：500 条评论页（库内 2 万评论）76ms；2 万评论全量加载 0.79s / 22.2MB；300 个单视频库时 `/api/videos` 聚合 1.82s、`/api/databases?include_details=1` 3.14s；前端进度轮询 900ms 一次，每次重建约 280 个 `Intl` 格式化器（实测 0.22–0.31ms/个 vs 复用 0.004ms），约 65ms 主线程。
