import type {
  ArchiveDeleteResponse,
  AuthQrPollResponse,
  AuthQrSession,
  CommentData,
  CookieStatus,
  DatabaseImportResponse,
  DatabaseListResponse,
  DatabaseExportResponse,
  DanmakuData,
  ParseVideoResponse,
  ProgressState,
  SpaceArchiveResponse,
  VideoListResponse,
} from "../types";

type LogFields = Record<string, string | number | boolean | null | undefined>;
type RequestOptions = RequestInit & { signal?: AbortSignal };

const MUTATING_REQUEST_HEADER = "X-Bilibili-Tool-Request";

export async function fetchDatabases(activeId = "main", options: { includeDetails?: boolean } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()), db_id: activeId });
  if (options.includeDetails === false) query.set("include_details", "0");
  return requestJson<DatabaseListResponse>("databases.list", `/api/databases?${query.toString()}`, { cache: "no-store" });
}

export async function fetchCookieStatus() {
  return requestJson<CookieStatus>("cookie.status", `/api/cookie/status?ts=${Date.now()}`, { cache: "no-store" });
}

export async function saveCookie(cookie: string) {
  return requestJson<CookieStatus>(
    "cookie.save",
    `/api/cookie/save?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookie }),
    },
    { length: cookie.length },
  );
}

export async function clearCookie() {
  return requestJson<CookieStatus>(
    "cookie.clear",
    `/api/cookie/clear?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
    },
  );
}

export async function createAuthQrCode() {
  return requestJson<AuthQrSession>(
    "auth.qrcode",
    `/api/auth/qrcode?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
    },
  );
}

export async function pollAuthQrCode(sessionId: string) {
  return requestJson<AuthQrPollResponse>(
    "auth.qrcode_poll",
    `/api/auth/qrcode/poll?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    },
    { session_id: sessionId.slice(0, 12) },
  );
}

export async function importDatabase(path: string) {
  return requestJson<DatabaseImportResponse>(
    "databases.import",
    `/api/databases/import?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
    { path: path.slice(0, 120) },
  );
}

export async function importDatabaseFiles(files: File[]) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));
  return requestJson<DatabaseImportResponse>(
    "databases.import_file",
    `/api/databases/import-file?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      body: form,
    },
    { file_count: files.length },
  );
}

export async function fetchCommentData(bvid?: string, dbId = "main", options: { limit?: number; offset?: number; signal?: AbortSignal } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  if (options.limit) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  appendDbId(query, dbId);
  return requestJson<CommentData>("comments.load", `/api/comments?${query.toString()}`, { cache: "no-store", signal: options.signal }, { bvid, db_id: dbId });
}

export async function fetchVideos(dbId = "main", options: { includeMeta?: boolean; limit?: number; offset?: number; signal?: AbortSignal } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (options.limit) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  if (options.includeMeta === false) query.set("include_meta", "0");
  appendDbId(query, dbId);
  return requestJson<VideoListResponse>("videos.list", `/api/videos?${query.toString()}`, { cache: "no-store", signal: options.signal }, { db_id: dbId, limit: options.limit, offset: options.offset });
}

export async function fetchDanmakuData(bvid?: string, dbId = "main", options: { limit?: number | null; offset?: number; signal?: AbortSignal } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  if (options.limit !== undefined && options.limit !== null) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  appendDbId(query, dbId);
  return requestJson<DanmakuData>("danmaku.load", `/api/danmaku?${query.toString()}`, { cache: "no-store", signal: options.signal }, { bvid, db_id: dbId, limit: options.limit });
}

export async function refreshDanmakuData(bvid?: string, dbId = "main") {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  appendDbId(query, dbId);
  return requestJson<DanmakuData>(
    "danmaku.refresh",
    `/api/danmaku/refresh?${query.toString()}`,
    {
      cache: "no-store",
      method: "POST",
    },
    { bvid, db_id: dbId },
  );
}

export async function parseVideo(url: string, delay: number, dbId = "main") {
  return requestJson<ParseVideoResponse>(
    "videos.parse",
    `/api/videos/parse?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, delay, db_id: dbId }),
    },
    { delay, video_ref: summarizeVideoRef(url), db_id: dbId },
  );
}

export async function archiveSpaceVideos(ownerRef: string, options: { delay: number; dbId?: string }) {
  return requestJson<SpaceArchiveResponse>(
    "space.archive",
    `/api/space/archive?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        owner_ref: ownerRef,
        delay: options.delay,
        db_id: options.dbId || "main",
      }),
    },
    { owner_ref: summarizeOwnerRef(ownerRef), delay: options.delay, db_id: options.dbId || "main" },
  );
}

export type TaskControlAction = "pause" | "resume" | "stop" | "retry" | "clear";

export async function controlSpaceTasks(action: TaskControlAction, taskId?: string) {
  return requestJson<{ ok: boolean; action: string; queue: ProgressState["queue"] }>(
    "space.control",
    `/api/space/tasks/control?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, task_id: taskId }),
    },
    { action, task_id: taskId },
  );
}

export async function exportDatabaseArchive(payload: { bvid?: string; bvids?: string[]; owner_mid?: string; label?: string; db_id?: string; format?: "sqlite" | "json" }) {
  return requestJson<DatabaseExportResponse>(
    "database.export",
    `/api/database/export?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    {
      bvid: payload.bvid,
      db_id: payload.db_id,
      format: payload.format,
      owner_mid: payload.owner_mid,
      video_count: payload.bvids?.length,
    },
  );
}

export async function openLocalPath(path: string) {
  return requestJson<{ ok: boolean; path: string; relative_path: string }>(
    "system.open_path",
    `/api/system/open-path?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
    { path },
  );
}

export async function deleteArchiveData(payload: { bvid?: string; bvids?: string[]; owner_mid?: string; db_id?: string }) {
  return requestJson<ArchiveDeleteResponse>(
    "archive.delete",
    `/api/archive/delete?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    {
      bvid: payload.bvid,
      db_id: payload.db_id,
      owner_mid: payload.owner_mid,
      video_count: payload.bvids?.length,
    },
  );
}

export async function refreshCommentData(bvid?: string, dbId = "main") {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  appendDbId(query, dbId);
  return requestJson<CommentData>(
    "comments.refresh",
    `/api/refresh?${query.toString()}`,
    {
      cache: "no-store",
      method: "POST",
    },
    { bvid, db_id: dbId },
  );
}

export async function fetchProgress() {
  const response = await fetch(`/api/progress?ts=${Date.now()}`, { cache: "no-store" });
  return parseJsonResponse<ProgressState>(response);
}

export function logClientEvent(event: string, message = "", fields: LogFields = {}) {
  const payload = JSON.stringify({
    event,
    message,
    page: window.location.pathname,
    ts: new Date().toISOString(),
    fields: {
      ...fields,
      href: window.location.href,
    },
  });

  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      navigator.sendBeacon("/api/logs/client", blob);
      return;
    }
  } catch {
    // Logging should never block the user's workflow.
  }

  try {
    void fetch("/api/logs/client", {
      body: payload,
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      method: "POST",
    });
  } catch {
    // Ignore client-side logging failures.
  }
}

async function requestJson<T>(event: string, url: string, init?: RequestOptions, fields: LogFields = {}) {
  const startedAt = performance.now();
  const method = init?.method || "GET";
  const path = summarizeApiPath(url);
  logClientEvent(`client.api.${event}.start`, "API request started", { ...fields, method, path });

  try {
    const response = await fetch(url, withMutatingRequestHeader(init));
    const payload = await parseJsonResponse<T>(response);
    logClientEvent(`client.api.${event}.success`, "API request succeeded", {
      ...fields,
      duration_ms: Math.round(performance.now() - startedAt),
      method,
      path,
      status: response.status,
    });
    return payload;
  } catch (reason: unknown) {
    logClientEvent(`client.api.${event}.error`, reason instanceof Error ? reason.message : String(reason), {
      ...fields,
      duration_ms: Math.round(performance.now() - startedAt),
      method,
      path,
    });
    throw reason;
  }
}

function withMutatingRequestHeader(init?: RequestOptions): RequestInit | undefined {
  const method = (init?.method || "GET").toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return init;
  const headers = new Headers(init?.headers);
  headers.set(MUTATING_REQUEST_HEADER, "1");
  return { ...init, headers };
}

async function parseJsonResponse<T>(response: Response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    const text = await response.text();
    const isHtml = text.trimStart().startsWith("<!doctype") || text.trimStart().startsWith("<html");
    if (isHtml) {
      throw new Error("后端 API 返回了前端页面，请重启后端服务或确认当前端口运行的是最新版本");
    }
    throw new Error(`后端返回了非 JSON 响应：${response.status}`);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: string; error?: string };
      detail = payload.error || payload.detail || "";
    } catch {
      detail = "";
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function summarizeApiPath(url: string) {
  return url.split("?")[0];
}

function appendDbId(query: URLSearchParams, dbId?: string) {
  if (dbId && dbId !== "main") {
    query.set("db_id", dbId);
  }
}

function summarizeVideoRef(value: string) {
  return value.match(/BV[0-9A-Za-z]{10}/)?.[0] || value.slice(0, 120);
}

function summarizeOwnerRef(value: string) {
  return value.match(/space\.bilibili\.com\/(\d+)/)?.[1] || value.match(/^\d+$/)?.[0] || value.slice(0, 120);
}
