import type {
  CommentData,
  DatabaseExportResponse,
  DanmakuData,
  ParseVideoResponse,
  ProgressState,
  SpaceArchiveResponse,
  VideoListResponse,
} from "../types";

type LogFields = Record<string, string | number | boolean | null | undefined>;

export async function fetchCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  return requestJson<CommentData>("comments.load", `/api/comments?${query.toString()}`, { cache: "no-store" }, { bvid });
}

export async function fetchVideos() {
  return requestJson<VideoListResponse>("videos.list", `/api/videos?ts=${Date.now()}`, { cache: "no-store" });
}

export async function fetchDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  return requestJson<DanmakuData>("danmaku.load", `/api/danmaku?${query.toString()}`, { cache: "no-store" }, { bvid });
}

export async function refreshDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  return requestJson<DanmakuData>(
    "danmaku.refresh",
    `/api/danmaku/refresh?${query.toString()}`,
    {
      cache: "no-store",
      method: "POST",
    },
    { bvid },
  );
}

export async function parseVideo(url: string, delay: number) {
  return requestJson<ParseVideoResponse>(
    "videos.parse",
    `/api/videos/parse?ts=${Date.now()}`,
    {
      cache: "no-store",
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, delay }),
    },
    { delay, video_ref: summarizeVideoRef(url) },
  );
}

export async function archiveSpaceVideos(ownerRef: string, options: { delay: number }) {
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
      }),
    },
    { owner_ref: summarizeOwnerRef(ownerRef), delay: options.delay },
  );
}

export async function exportDatabaseArchive(payload: { bvid?: string; bvids?: string[]; owner_mid?: string; label?: string }) {
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
      owner_mid: payload.owner_mid,
      video_count: payload.bvids?.length,
    },
  );
}

export async function refreshCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  return requestJson<CommentData>(
    "comments.refresh",
    `/api/refresh?${query.toString()}`,
    {
      cache: "no-store",
      method: "POST",
    },
    { bvid },
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

async function requestJson<T>(event: string, url: string, init?: RequestInit, fields: LogFields = {}) {
  const startedAt = performance.now();
  const method = init?.method || "GET";
  const path = summarizeApiPath(url);
  logClientEvent(`client.api.${event}.start`, "API request started", { ...fields, method, path });

  try {
    const response = await fetch(url, init);
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

async function parseJsonResponse<T>(response: Response) {
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

function summarizeVideoRef(value: string) {
  return value.match(/BV[0-9A-Za-z]{10}/)?.[0] || value.slice(0, 120);
}

function summarizeOwnerRef(value: string) {
  return value.match(/space\.bilibili\.com\/(\d+)/)?.[1] || value.match(/^\d+$/)?.[0] || value.slice(0, 120);
}
