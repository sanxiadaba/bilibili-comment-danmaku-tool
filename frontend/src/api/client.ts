import type { CommentData, DanmakuData, ParseVideoResponse, ProgressState, VideoListResponse } from "../types";

export async function fetchCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/comments?${query.toString()}`, { cache: "no-store" });
  return parseJsonResponse<CommentData>(response);
}

export async function fetchVideos() {
  const response = await fetch(`/api/videos?ts=${Date.now()}`, { cache: "no-store" });
  return parseJsonResponse<VideoListResponse>(response);
}

export async function fetchDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/danmaku?${query.toString()}`, { cache: "no-store" });
  return parseJsonResponse<DanmakuData>(response);
}

export async function refreshDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/danmaku/refresh?${query.toString()}`, {
    cache: "no-store",
    method: "POST",
  });
  return parseJsonResponse<DanmakuData>(response);
}

export async function parseVideo(url: string, delay: number) {
  const response = await fetch(`/api/videos/parse?ts=${Date.now()}`, {
    cache: "no-store",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, delay }),
  });
  return parseJsonResponse<ParseVideoResponse>(response);
}

export async function refreshCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/refresh?${query.toString()}`, {
    cache: "no-store",
    method: "POST",
  });
  return parseJsonResponse<CommentData>(response);
}

export async function fetchProgress() {
  const response = await fetch(`/api/progress?ts=${Date.now()}`, { cache: "no-store" });
  return parseJsonResponse<ProgressState>(response);
}

async function parseJsonResponse<T>(response: Response) {
  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { error?: string };
      detail = payload.error || "";
    } catch {
      detail = "";
    }
    throw new Error(detail ? `HTTP ${response.status}: ${detail}` : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}
