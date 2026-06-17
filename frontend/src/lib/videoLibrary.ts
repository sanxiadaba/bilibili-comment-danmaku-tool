import type { OwnerGroup, OwnerSummary, VideoSummary } from "../types";

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

export function buildOwnerGroups(videos: VideoSummary[], ownerSummaries: OwnerSummary[] = []) {
  if (ownerSummaries.length) {
    const bvidsByOwner = new Map<string, string[]>();
    for (const video of videos) {
      const key = ownerKey(video);
      const bvids = bvidsByOwner.get(key);
      if (bvids) {
        bvids.push(video.bvid);
      } else {
        bvidsByOwner.set(key, [video.bvid]);
      }
    }
    return ownerSummaries.map((owner) => ({
      bvids: owner.owner_mid ? [] : bvidsByOwner.get(owner.key) || [],
      key: owner.key,
      name: owner.name,
      ownerMid: owner.owner_mid,
      videoCount: owner.video_count,
      commentCount: owner.comment_count,
      danmakuCount: owner.danmaku_count,
      storageBytes: owner.storage_bytes,
    }));
  }

  const groups = new Map<string, OwnerGroup>();
  for (const video of videos) {
    const key = ownerKey(video);
    const existing = groups.get(key);
    if (existing) {
      existing.bvids.push(video.bvid);
      existing.videoCount += 1;
      existing.commentCount += video.comment_total_count || 0;
      existing.danmakuCount += video.danmaku_count || 0;
      existing.storageBytes = estimateOwnerStorageBytes(existing.commentCount, existing.danmakuCount, existing.videoCount);
    } else {
      groups.set(key, {
        bvids: [video.bvid],
        key,
        name: ownerName(video),
        ownerMid: (video.owner_mid || "").trim(),
        videoCount: 1,
        commentCount: video.comment_total_count || 0,
        danmakuCount: video.danmaku_count || 0,
        storageBytes: estimateOwnerStorageBytes(video.comment_total_count || 0, video.danmaku_count || 0, 1),
      });
    }
  }

  return Array.from(groups.values()).sort((first, second) => {
    if (second.videoCount !== first.videoCount) return second.videoCount - first.videoCount;
    if (second.commentCount !== first.commentCount) return second.commentCount - first.commentCount;
    return first.name.localeCompare(second.name, "zh-Hans-CN");
  });
}

export function mergeVideosByBvid(current: VideoSummary[], incoming: VideoSummary[]) {
  const byBvid = new Map(current.map((video) => [video.bvid, video]));
  for (const video of incoming) {
    byBvid.set(video.bvid, video);
  }
  return Array.from(byBvid.values());
}

export function singleDatabaseIdForVideos(videos: VideoSummary[], fallbackDbId: string) {
  const ids = new Set(videos.map((video) => video.db_id || fallbackDbId));
  return ids.size === 1 ? Array.from(ids)[0] : "";
}

export function estimateOwnerStorageBytes(commentCount: number, danmakuCount: number, videoCount: number) {
  return commentCount * 900 + danmakuCount * 260 + videoCount * 4096;
}
