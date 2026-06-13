export type NormalizedUser = {
  mid: string;
  uname: string;
  sex?: string;
  sign?: string;
  avatar?: string;
  level?: number;
  vip?: unknown;
  official_verify?: unknown;
  pendant?: unknown;
  nameplate?: unknown;
};

export type CommentPicture = {
  img_src: string;
  img_width?: number;
  img_height?: number;
  img_size?: number;
  top_right_icon?: string;
  play_gif_thumbnail?: boolean;
};

export type CommentEmote = {
  text?: string;
  url?: string;
  jump_title?: string;
  meta?: {
    size?: number;
    suggest?: string[];
  };
  [key: string]: unknown;
};

export type CommentTextPart =
  | {
      type: "text";
      text: string;
    }
  | {
      type: "emote";
      text: string;
      title: string;
      url: string;
      size?: number;
    };

export type NormalizedComment = {
  level: 1 | 2;
  rpid: string;
  oid: string;
  type: number;
  mid: string;
  root: string;
  parent: string;
  dialog: string;
  ctime: number;
  time_iso: string;
  time_iso_utc: string;
  like: number;
  rcount: number;
  count: number;
  state: number;
  attr: number;
  message: string;
  emote?: Record<string, CommentEmote>;
  pictures?: CommentPicture[];
  jump_url?: Record<string, unknown>;
  ip_location?: string;
  first_seen_at?: string;
  last_seen_at?: string;
  missing_since?: string;
  is_deleted?: boolean;
  is_up_owner?: boolean;
  user: NormalizedUser;
};

export type CommentNode = {
  normalized: NormalizedComment;
  replies?: CommentNode[];
  raw: Record<string, unknown>;
};

export type CommentData = {
  metadata: {
    source_url: string;
    bvid: string;
    aid: number;
    title: string;
    fetched_at: string;
    sort: string;
    api_comment_count: number;
    top_level_comment_count: number;
    expected_nested_comment_count: number;
    nested_comment_count: number;
    comment_total_count: number;
    active_comment_count?: number;
    deleted_comment_count?: number;
    child_fetch_summary: Array<Record<string, unknown>>;
    notes: string[];
  };
  video_raw: {
    pic?: string;
    cid?: string;
    owner?: {
      mid?: string;
      name?: string;
      face?: string;
    };
    stat?: {
      view?: number;
      danmaku?: number;
      reply?: number;
      favorite?: number;
      coin?: number;
      share?: number;
      like?: number;
    };
    pubdate?: number;
    desc?: string;
    duration?: number;
  } & Record<string, unknown>;
  comments: CommentNode[];
  comment_items: CommentNode[];
  refresh?: {
    before_count: number;
    scraped_count?: number;
    after_count: number;
    active_count?: number;
    deleted_count?: number;
    added_count: number;
    danmaku_count?: number;
    warning?: string;
    logs?: string[];
  };
};

export type DanmakuItem = {
  dmid: string;
  bvid: string;
  cid?: string;
  progress: number;
  mode: number;
  font_size: number;
  color: number;
  ctime: number;
  pool: number;
  user_hash?: string;
  weight?: number;
  like_count?: number;
  is_up_owner?: boolean;
  content: string;
  fetched_at: string;
};

export type DanmakuData = {
  metadata: {
    bvid: string;
    cid?: string;
    title: string;
    duration?: number;
    total_count: number;
    fetched_at?: string;
    min_progress?: number;
    max_progress?: number;
    limit: number;
  };
  items: DanmakuItem[];
  buckets: Array<{
    bucket_start: number;
    label: string;
    count: number;
  }>;
  refresh?: {
    before_count: number;
    after_count: number;
    scraped_count: number;
    logs?: string[];
    warning?: string;
  };
};

export type VideoSummary = {
  bvid: string;
  aid: number;
  title: string;
  source_url: string;
  fetched_at: string;
  pic?: string;
  video_cid?: string;
  owner_mid?: string;
  owner_name?: string;
  owner_face?: string;
  stat_view?: number;
  stat_reply?: number;
  stat_like?: number;
  comment_total_count: number;
  active_comment_count: number;
  deleted_comment_count: number;
  top_level_comment_count: number;
  nested_comment_count: number;
  comment_like_count: number;
  latest_comment_ctime?: number;
  danmaku_count: number;
  latest_danmaku_fetched_at?: string;
};

export type VideoListResponse = {
  videos: VideoSummary[];
  database?: DatabaseInfo;
};

export type ParseVideoResponse = {
  ok?: boolean;
  bvid: string;
  task_id?: string;
  queue_position?: number;
  message?: string;
  before_count?: number;
  scraped_count?: number;
  after_count?: number;
  active_count?: number;
  deleted_count?: number;
  danmaku_count?: number;
  video?: VideoSummary;
  logs?: string[];
};

export type SpaceArchiveResponse = {
  ok: boolean;
  mid: string;
  task_id: string;
  queue_position: number;
  message: string;
  delay: number;
  between_videos_min: number;
  between_videos_max: number;
  no_cache: boolean;
};

export type CookieStatus = {
  exists: boolean;
  path: string;
  length: number;
  status: "missing" | "empty" | "unchecked" | "valid" | "invalid" | "error" | string;
  message: string;
  has_sessdata: boolean;
  has_bili_jct: boolean;
  has_dede_user_id: boolean;
  has_browser_id: boolean;
  bili_ticket_expires_at: string;
  bili_ticket_expired: boolean;
  nav_checked: boolean;
  nav_code: number | null;
  nav_message: string;
  is_login: boolean;
  mid_present: boolean;
  uname_present: boolean;
  wbi_present: boolean;
};

export type DatabaseExportResponse = {
  ok: boolean;
  path: string;
  relative_path: string;
  file_name: string;
  format: "sqlite" | "json" | string;
  json_path?: string;
  json_relative_path?: string;
  json_file_name?: string;
  database?: DatabaseInfo;
  video_count: number;
  bvids: string[];
  counts: Record<string, number>;
  manifest?: Record<string, unknown>;
  size_bytes: number;
};

export type DatabaseInfo = {
  id: string;
  role: "main" | "hotplug" | "legacy_export" | string;
  name: string;
  file_name: string;
  path: string;
  relative_path: string;
  exists: boolean;
  size_bytes: number;
  video_count: number;
  comment_count: number;
  danmaku_count: number;
  owner_count: number;
  archive_kind: "main" | "up" | "video" | "collection" | "unknown" | string;
  archive_label: string;
  owner_mid: string;
  owner_name: string;
  bvids: string[];
  coverage_status: "unique" | "duplicate" | "overlap" | "has_better" | string;
  coverage_message: string;
  overlap_count: number;
  duplicate_database_ids: string[];
  better_database_ids: string[];
  updated_at: string;
  ok: boolean;
  error: string;
};

export type DatabaseListResponse = {
  databases: DatabaseInfo[];
  active_id: string;
  hotplug_dir: string;
  legacy_export_dir: string;
};

export type DatabaseImportResponse = {
  ok: boolean;
  database: DatabaseInfo;
  databases?: DatabaseInfo[];
  imported_count?: number;
  errors?: string[];
};

export type ProgressTask = {
  id: string;
  kind: string;
  mid: string;
  owner_ref: string;
  bvid?: string;
  video_ref?: string;
  status: "queued" | "waiting" | "running" | "finished" | "failed" | string;
  message: string;
  created_at: string;
  updated_at: string;
  started_at: string;
  finished_at: string;
  progress: number;
  current_bvid: string;
  total: number;
  complete: number;
  archived: number;
  skipped: number;
  failed: number;
  queue_position?: number;
  pause_requested?: boolean;
  stop_requested?: boolean;
};

export type ProgressQueue = {
  active: ProgressTask | null;
  queued: ProgressTask[];
  recent: ProgressTask[];
};

export type ProgressState = {
  active: boolean;
  kind: string;
  bvid: string;
  message: string;
  logs: string[];
  percent: number;
  stage: string;
  stats: Record<string, string | number>;
  started_at: string;
  updated_at: string;
  done: boolean;
  error?: string;
  queue?: ProgressQueue;
};

export type SortMode = "time_asc" | "time_desc" | "like_desc" | "reply_desc";

export type LevelFilter = "all" | "top" | "reply" | "owner";

