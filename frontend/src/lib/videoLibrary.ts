import type { VideoSummary } from "../types";

export function extractBvid(value: string) {
  return value.trim().match(/BV[0-9A-Za-z]{10}/)?.[0] || "";
}

export function initialDatabaseId() {
  const fromUrl = new URLSearchParams(window.location.search).get("db_id");
  if (fromUrl) {
    window.localStorage.setItem("bilibili-active-db-id", fromUrl);
    return fromUrl;
  }
  return window.localStorage.getItem("bilibili-active-db-id") || "main";
}

export function dbPath(path: string, dbId: string) {
  if (!dbId || dbId === "main") return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}db_id=${encodeURIComponent(dbId)}`;
}

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function summarizeOwnerRef(value: string) {
  return value.match(/space\.bilibili\.com\/(\d+)/)?.[1] || value.match(/^\d+$/)?.[0] || value.slice(0, 120);
}

export function ownerName(video: VideoSummary) {
  return (video.owner_name || "未知UP主").trim() || "未知UP主";
}

export function ownerKey(video: VideoSummary) {
  const mid = (video.owner_mid || "").trim();
  if (mid) return `mid:${mid}`;
  return `name:${ownerName(video).toLowerCase()}`;
}
