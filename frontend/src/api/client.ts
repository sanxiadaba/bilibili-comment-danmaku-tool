// 所有后端接口都从这里出：一个接口一个函数，写操作自动带本机防护头。

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
  TaskControlAction,
  VideoListResponse,
} from "../types";

type RequestOptions = RequestInit & { signal?: AbortSignal; timeoutMs?: number };

const MUTATING_REQUEST_HEADER = "X-Bilibili-Tool-Request";
const POST_REQUEST: RequestOptions = { cache: "no-store", method: "POST" };
const DEFAULT_TIMEOUT_MS = 60_000;
// Refreshes scrape Bilibili page by page and can legitimately run for minutes.
const NO_TIMEOUT = 0;

export async function fetchDatabases(
  activeId = "main",
  options: { includeDetails?: boolean; signal?: AbortSignal } = {},
) {
  const query = new URLSearchParams({ ts: String(Date.now()), db_id: activeId });
  if (options.includeDetails === false) query.set("include_details", "0");
  return requestJson<DatabaseListResponse>(`/api/databases?${query.toString()}`, {
    cache: "no-store",
    signal: options.signal,
  });
}

export async function fetchCookieStatus() {
  return requestJson<CookieStatus>(`/api/cookie/status?ts=${Date.now()}`, { cache: "no-store" });
}

export async function saveCookie(cookie: string) {
  return requestJson<CookieStatus>(`/api/cookie/save?ts=${Date.now()}`, postJsonInit({ cookie }));
}

export async function clearCookie() {
  return requestJson<CookieStatus>(`/api/cookie/clear?ts=${Date.now()}`, POST_REQUEST);
}

export async function createAuthQrCode() {
  return requestJson<AuthQrSession>(`/api/auth/qrcode?ts=${Date.now()}`, POST_REQUEST);
}

export async function pollAuthQrCode(sessionId: string) {
  return requestJson<AuthQrPollResponse>(`/api/auth/qrcode/poll?ts=${Date.now()}`, postJsonInit({ session_id: sessionId }));
}

export async function importDatabase(path: string) {
  return requestJson<DatabaseImportResponse>(`/api/databases/import?ts=${Date.now()}`, postJsonInit({ path }));
}

export async function importDatabaseFiles(files: File[]) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));
  return requestJson<DatabaseImportResponse>(`/api/databases/import-file?ts=${Date.now()}`, {
      cache: "no-store",
      method: "POST",
      body: form,
    });
}

export async function fetchCommentData(bvid?: string, dbId = "main", options: { limit?: number; offset?: number; signal?: AbortSignal } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  if (options.limit) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  appendDbId(query, dbId);
  return requestJson<CommentData>(`/api/comments?${query.toString()}`, { cache: "no-store", signal: options.signal });
}

export async function fetchVideos(
  dbId = "main",
  options: {
    includeMeta?: boolean;
    limit?: number;
    offset?: number;
    query?: string;
    ownerKey?: string;
    signal?: AbortSignal;
  } = {},
) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (options.limit) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  if (options.includeMeta === false) query.set("include_meta", "0");
  if (options.query) query.set("q", options.query);
  if (options.ownerKey && options.ownerKey !== "all") query.set("owner", options.ownerKey);
  appendDbId(query, dbId);
  return requestJson<VideoListResponse>(`/api/videos?${query.toString()}`, { cache: "no-store", signal: options.signal });
}

export async function fetchDanmakuData(bvid?: string, dbId = "main", options: { limit?: number | null; offset?: number; signal?: AbortSignal } = {}) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  if (options.limit !== undefined && options.limit !== null) query.set("limit", String(options.limit));
  if (options.offset) query.set("offset", String(options.offset));
  appendDbId(query, dbId);
  return requestJson<DanmakuData>(`/api/danmaku?${query.toString()}`, { cache: "no-store", signal: options.signal });
}

export async function refreshDanmakuData(bvid?: string, dbId = "main") {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  appendDbId(query, dbId);
  return requestJson<DanmakuData>(`/api/danmaku/refresh?${query.toString()}`, { ...POST_REQUEST, timeoutMs: NO_TIMEOUT });
}

export async function parseVideo(url: string, delay: number, dbId = "main") {
  return requestJson<ParseVideoResponse>(`/api/videos/parse?ts=${Date.now()}`, postJsonInit({ url, delay, db_id: dbId }));
}

export async function archiveSpaceVideos(ownerRef: string, options: { delay: number; dbId?: string }) {
  return requestJson<SpaceArchiveResponse>(`/api/space/archive?ts=${Date.now()}`, postJsonInit({
      owner_ref: ownerRef,
      delay: options.delay,
      db_id: options.dbId || "main",
    }));
}

export async function controlSpaceTasks(action: TaskControlAction, taskId?: string) {
  return requestJson<{ ok: boolean; action: string; queue: ProgressState["queue"] }>(`/api/space/tasks/control?ts=${Date.now()}`, postJsonInit({ action, task_id: taskId }));
}

export async function exportDatabaseArchive(payload: { bvid?: string; bvids?: string[]; owner_mid?: string; label?: string; db_id?: string; format?: "sqlite" | "json" }) {
  return requestJson<DatabaseExportResponse>(`/api/database/export?ts=${Date.now()}`, postJsonInit(payload));
}

export async function openLocalPath(path: string) {
  return requestJson<{ ok: boolean; path: string; relative_path: string }>(`/api/system/open-path?ts=${Date.now()}`, postJsonInit({ path }));
}

export async function deleteArchiveData(payload: { bvid?: string; bvids?: string[]; owner_mid?: string; db_id?: string }) {
  return requestJson<ArchiveDeleteResponse>(`/api/archive/delete?ts=${Date.now()}`, postJsonInit(payload));
}

export async function stopRunningTask(kind: "comments" | "danmaku" | "all" = "all") {
  return requestJson<{ ok: boolean; kind: string; message: string }>(`/api/tasks/stop?ts=${Date.now()}`, postJsonInit({ kind }));
}

export async function refreshCommentData(bvid?: string, dbId = "main") {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  appendDbId(query, dbId);
  return requestJson<CommentData>(`/api/refresh?${query.toString()}`, { ...POST_REQUEST, timeoutMs: NO_TIMEOUT });
}

export async function fetchProgress(signal?: AbortSignal) {
  const response = await fetch(`/api/progress?ts=${Date.now()}`, withSignalTimeout({ cache: "no-store", signal }));
  return parseJsonResponse<ProgressState>(response);
}

async function requestJson<T>(url: string, init?: RequestOptions) {
  try {
    const response = await fetch(url, withMutatingRequestHeader(withSignalTimeout(init)));
    return await parseJsonResponse<T>(response);
  } catch (reason: unknown) {
    if (reason instanceof DOMException && reason.name === "TimeoutError") {
      throw new Error(`请求超时（${Math.round(DEFAULT_TIMEOUT_MS / 1000)} 秒），后端可能正在处理长任务`);
    }
    throw reason;
  }
}

/** Bound every request so a stalled backend cannot leave the UI on a spinner forever. */
function withSignalTimeout(init?: RequestOptions): RequestOptions | undefined {
  if (!init) return init;
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init;
  if (!timeoutMs || typeof AbortSignal === "undefined" || typeof AbortSignal.timeout !== "function") return rest;
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!rest.signal) return { ...rest, signal: timeoutSignal };
  if (typeof AbortSignal.any === "function") {
    return { ...rest, signal: AbortSignal.any([rest.signal, timeoutSignal]) };
  }
  return rest;
}

function postJsonInit(body: unknown): RequestOptions {
  return { ...POST_REQUEST, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
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

function appendDbId(query: URLSearchParams, dbId?: string) {
  if (dbId && dbId !== "main") {
    query.set("db_id", dbId);
  }
}

