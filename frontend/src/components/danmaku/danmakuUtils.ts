import type { DanmakuItem } from "../../types";

export type DanmakuSortMode = "progress_asc" | "progress_desc" | "like_desc" | "time_desc" | "content_asc";
export type DanmakuModeFilter = "all" | "scroll" | "top" | "bottom" | "other";

export const danmakuSortLabels: Record<DanmakuSortMode, string> = {
  progress_asc: "视频时间升序",
  progress_desc: "视频时间降序",
  like_desc: "点赞优先",
  time_desc: "发送时间最新",
  content_asc: "内容 A-Z",
};

export const danmakuModeLabels: Record<DanmakuModeFilter, string> = {
  all: "全部",
  scroll: "滚动",
  top: "顶部",
  bottom: "底部",
  other: "其他",
};

export type DanmakuBucket = {
  bucket_start: number;
  label: string;
  count: number;
};

export function formatProgress(seconds?: number) {
  const value = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function sortDanmakuItems(items: DanmakuItem[], sortMode: DanmakuSortMode) {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (sortMode === "progress_desc") return b.progress - a.progress || b.dmid.localeCompare(a.dmid);
    if (sortMode === "like_desc") return (b.like_count || 0) - (a.like_count || 0) || a.progress - b.progress;
    if (sortMode === "time_desc") return b.ctime - a.ctime || b.dmid.localeCompare(a.dmid);
    if (sortMode === "content_asc") return a.content.localeCompare(b.content, "zh-CN") || a.progress - b.progress;
    return a.progress - b.progress || a.dmid.localeCompare(b.dmid);
  });
  return sorted;
}

export function buildDanmakuBuckets(items: DanmakuItem[]): DanmakuBucket[] {
  const buckets = new Map<number, number>();
  for (const item of items) {
    const bucketStart = Math.floor((item.progress || 0) / 10) * 10;
    buckets.set(bucketStart, (buckets.get(bucketStart) || 0) + 1);
  }
  return [...buckets.entries()]
    .map(([bucket_start, count]) => ({ bucket_start, label: formatProgress(bucket_start), count }))
    .sort((a, b) => a.bucket_start - b.bucket_start);
}

export function buildDanmakuModeStats(items: DanmakuItem[]) {
  const counts = new Map<DanmakuModeFilter, number>([
    ["scroll", 0],
    ["top", 0],
    ["bottom", 0],
    ["other", 0],
  ]);
  for (const item of items) {
    const mode = getDanmakuModeGroup(item.mode);
    if (mode !== "all") counts.set(mode, (counts.get(mode) || 0) + 1);
  }
  return [...counts.entries()].map(([mode, count]) => ({ mode, label: danmakuModeLabels[mode], count }));
}

export function buildDanmakuColorStats(items: DanmakuItem[]) {
  const counts = new Map<number, number>();
  for (const item of items) {
    counts.set(item.color, (counts.get(item.color) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([color, count]) => ({ color, label: colorNameForDanmaku(color), count }))
    .sort((a, b) => b.count - a.count || a.color - b.color);
}

export function buildRepeatedDanmakuContent(items: DanmakuItem[]) {
  const buckets = new Map<string, { content: string; count: number; sample: DanmakuItem }>();
  for (const item of items) {
    const content = item.content.trim();
    if (!content) continue;
    const current = buckets.get(content) || { content, count: 0, sample: item };
    current.count += 1;
    if (item.progress < current.sample.progress) current.sample = item;
    buckets.set(content, current);
  }
  return [...buckets.values()]
    .filter((item) => item.count > 1)
    .sort((a, b) => b.count - a.count || a.sample.progress - b.sample.progress);
}

export function getDanmakuModeGroup(mode: number): DanmakuModeFilter {
  if (mode === 1 || mode === 2 || mode === 3) return "scroll";
  if (mode === 5) return "top";
  if (mode === 4) return "bottom";
  return "other";
}

export function getDanmakuModeLabel(mode: number) {
  const group = getDanmakuModeGroup(mode);
  if (group === "other") return `模式 ${mode}`;
  return danmakuModeLabels[group];
}

export function colorNumberToHex(color: number) {
  const normalized = Math.max(0, Math.min(0xffffff, color || 0));
  return `#${normalized.toString(16).padStart(6, "0").toUpperCase()}`;
}

export function colorNameForDanmaku(color: number) {
  const names: Record<number, string> = {
    0xffffff: "白色",
    0xe70012: "红色",
    0xfe0302: "红色",
    0xff7204: "橙色",
    0xffaa02: "橙色",
    0xffff00: "黄色",
    0xfef102: "黄色",
    0x00cd00: "绿色",
    0x89d5ff: "浅蓝",
    0x00a1d6: "蓝色",
    0x0000ff: "蓝色",
    0xe2027f: "粉色",
    0x7b00ff: "紫色",
    0x000000: "黑色",
  };
  return names[Math.max(0, Math.min(0xffffff, color || 0))] || "自定义颜色";
}
