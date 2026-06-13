import type {
  CommentNode,
  CookieStatus,
  DanmakuItem,
  DatabaseInfo,
  ProgressState,
  ProgressTask,
  VideoSummary,
} from "../../../frontend/src/types";

export function makeVideo(overrides: Partial<VideoSummary> = {}): VideoSummary {
  return {
    aid: 1,
    bvid: "BV1xx411c7mD",
    title: "Test video",
    source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
    fetched_at: "2024-01-01T00:00:00+08:00",
    owner_mid: "42",
    owner_name: "Owner",
    stat_view: 1000,
    comment_total_count: 10,
    active_comment_count: 8,
    deleted_comment_count: 2,
    top_level_comment_count: 5,
    nested_comment_count: 5,
    comment_like_count: 20,
    danmaku_count: 3,
    ...overrides,
  };
}

export function makeComment(
  overrides: Partial<CommentNode["normalized"]> = {},
  replies: CommentNode[] = [],
): CommentNode {
  return {
    raw: {},
    replies,
    normalized: {
      level: 1,
      rpid: "1",
      oid: "100",
      type: 1,
      mid: "42",
      root: "0",
      parent: "0",
      dialog: "0",
      ctime: 1700000000,
      time_iso: "2024-01-01T00:00:00+08:00",
      time_iso_utc: "2023-12-31T16:00:00+00:00",
      like: 0,
      rcount: 0,
      count: 0,
      state: 0,
      attr: 0,
      message: "hello",
      user: {
        mid: "42",
        uname: "alice",
      },
      ...overrides,
    },
  };
}

export function makeDanmaku(overrides: Partial<DanmakuItem> = {}): DanmakuItem {
  return {
    dmid: "1",
    bvid: "BV1xx411c7mD",
    cid: "456",
    progress: 0,
    mode: 1,
    font_size: 25,
    color: 0xffffff,
    ctime: 1700000000,
    pool: 0,
    user_hash: "hash",
    weight: 0,
    like_count: 0,
    is_up_owner: false,
    content: "hello",
    fetched_at: "2024-01-01T00:00:00+00:00",
    ...overrides,
  };
}

export function makeProgress(overrides: Partial<ProgressState> = {}): ProgressState {
  return {
    active: true,
    kind: "parse",
    bvid: "BV1xx411c7mD",
    message: "working",
    logs: ["one", "two", "three", "four", "five"],
    percent: 45,
    stage: "Fetching",
    stats: { Pages: "2", Items: 20 },
    started_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    done: false,
    ...overrides,
  };
}

export function makeProgressTask(overrides: Partial<ProgressTask> = {}): ProgressTask {
  return {
    id: "task-1",
    kind: "space_archive",
    mid: "42",
    owner_ref: "https://space.bilibili.com/42",
    status: "running",
    message: "archiving",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    started_at: "2024-01-01T00:00:00Z",
    finished_at: "",
    progress: 55,
    current_bvid: "BV1xx411c7mD",
    total: 10,
    complete: 5,
    archived: 4,
    skipped: 1,
    failed: 0,
    ...overrides,
  };
}

export function makeCookieStatus(overrides: Partial<CookieStatus> = {}): CookieStatus {
  return {
    exists: true,
    path: "D:/data/cookie.txt",
    length: 1200,
    status: "valid",
    message: "Bilibili 已识别登录态",
    has_sessdata: true,
    has_bili_jct: true,
    has_dede_user_id: true,
    has_browser_id: true,
    bili_ticket_expires_at: "",
    bili_ticket_expired: false,
    nav_checked: true,
    nav_code: 0,
    nav_message: "0",
    is_login: true,
    mid_present: true,
    uname_present: true,
    wbi_present: true,
    ...overrides,
  };
}

export function makeDatabase(overrides: Partial<DatabaseInfo> = {}): DatabaseInfo {
  return {
    id: "main",
    role: "main",
    name: "Main archive",
    file_name: "comment_danmaku.db",
    path: "D:/data/comment_danmaku.db",
    relative_path: "data/comment_danmaku.db",
    exists: true,
    size_bytes: 1024,
    page_count: 8,
    page_size: 4096,
    freelist_count: 0,
    reclaimable_bytes: 0,
    used_bytes: 1024,
    wal_bytes: 0,
    storage_message: "数据库已整理，没有可回收空页",
    video_count: 2,
    comment_count: 20,
    danmaku_count: 8,
    owner_count: 1,
    top_owners: [
      {
        owner_mid: "42",
        owner_name: "Owner",
        video_count: 2,
        comment_count: 20,
        danmaku_count: 8,
      },
    ],
    archive_kind: "main",
    archive_label: "main",
    owner_mid: "42",
    owner_name: "Owner",
    bvids: ["BV1xx411c7mD"],
    coverage_status: "unique",
    coverage_message: "Unique archive",
    overlap_count: 0,
    duplicate_database_ids: [],
    better_database_ids: [],
    updated_at: "2024-01-01T00:00:00Z",
    ok: true,
    error: "",
    ...overrides,
  };
}
