import type {
  CommentNode,
  CommentPicture,
  CommentTextPart,
  LevelFilter,
  NormalizedComment,
  SortMode,
} from "../types";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatNumber(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "0";
  return new Intl.NumberFormat("zh-CN", {
    notation: value >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDateTime(iso?: string) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatFullDateTime(iso?: string) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

export function cleanIpLocation(value?: string) {
  return value?.replace("IP属地：", "").trim() || "未知";
}

export function getCommentText(comment: CommentNode) {
  return comment.normalized.message || "";
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function getCommentTextParts(normalized: NormalizedComment): CommentTextPart[] {
  const message = normalized.message || "";
  const emotes = normalized.emote || {};
  const keys = Object.keys(emotes)
    .filter((key) => Boolean(emotes[key]?.url) && message.includes(key))
    .sort((a, b) => b.length - a.length);

  if (!keys.length) {
    return message ? [{ type: "text", text: message }] : [];
  }

  const pattern = new RegExp(keys.map(escapeRegExp).join("|"), "g");
  const parts: CommentTextPart[] = [];
  let lastIndex = 0;

  for (const match of message.matchAll(pattern)) {
    const index = match.index ?? 0;
    const text = match[0];
    if (index > lastIndex) {
      parts.push({ type: "text", text: message.slice(lastIndex, index) });
    }

    const emote = emotes[text];
    if (emote?.url) {
      parts.push({
        type: "emote",
        text,
        title: emote.jump_title || emote.text || text,
        url: normalizeImageUrl(emote.url),
        size: emote.meta?.size,
      });
    } else {
      parts.push({ type: "text", text });
    }

    lastIndex = index + text.length;
  }

  if (lastIndex < message.length) {
    parts.push({ type: "text", text: message.slice(lastIndex) });
  }

  return parts;
}

export function getCommentAuthor(comment: CommentNode) {
  return comment.normalized.user?.uname || "未命名用户";
}

export function getCommentAvatar(comment?: CommentNode) {
  return normalizeImageUrl(comment?.normalized.user?.avatar);
}

export function normalizeImageUrl(value?: string) {
  if (!value) return "";
  if (value.startsWith("//")) return `https:${value}`;
  if (value.startsWith("http://")) return value.replace(/^http:\/\//, "https://");
  return value;
}

export function getCommentPictures(comment?: CommentNode): CommentPicture[] {
  return (comment?.normalized.pictures || [])
    .map((picture) => ({ ...picture, img_src: normalizeImageUrl(picture.img_src) }))
    .filter((picture) => Boolean(picture.img_src));
}

export function sortComments(comments: CommentNode[], sortMode: SortMode) {
  const sorted = [...comments];
  sorted.sort((a, b) => {
    const an = a.normalized;
    const bn = b.normalized;
    if (sortMode === "time_desc") return bn.ctime - an.ctime || Number(bn.rpid) - Number(an.rpid);
    if (sortMode === "like_desc") return (bn.like || 0) - (an.like || 0) || bn.ctime - an.ctime;
    if (sortMode === "reply_desc") return (bn.rcount || 0) - (an.rcount || 0) || bn.ctime - an.ctime;
    return an.ctime - bn.ctime || Number(an.rpid) - Number(bn.rpid);
  });
  return sorted;
}

export function filterComments(
  comments: CommentNode[],
  query: string,
  levelFilter: LevelFilter,
  location: string,
  minLikes: number,
) {
  const needle = query.trim().toLowerCase();
  return comments.filter((comment) => {
    const normalized = comment.normalized;
    const matchesLevel =
      levelFilter === "all" ||
      (levelFilter === "top" && normalized.level === 1) ||
      (levelFilter === "reply" && normalized.level === 2) ||
      (levelFilter === "owner" && normalized.is_up_owner);
    if (!matchesLevel) return false;
    if (location !== "all" && cleanIpLocation(normalized.ip_location) !== location) return false;
    if ((normalized.like || 0) < minLikes) return false;
    if (!needle) return true;
    const text = getCommentText(comment).toLowerCase();
    const author = getCommentAuthor(comment).toLowerCase();
    return text.includes(needle) || author.includes(needle) || normalized.rpid.includes(needle);
  });
}

export function hourlyBuckets(comments: CommentNode[]) {
  const buckets = new Map<string, { label: string; count: number; likes: number; timestamp: number }>();
  for (const comment of comments) {
    const date = new Date(comment.normalized.time_iso);
    date.setMinutes(0, 0, 0);
    const key = date.toISOString();
    const current = buckets.get(key) || {
      label: new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
      }).format(date),
      count: 0,
      likes: 0,
      timestamp: date.getTime(),
    };
    current.count += 1;
    current.likes += comment.normalized.like || 0;
    buckets.set(key, current);
  }
  return [...buckets.values()].sort((a, b) => a.timestamp - b.timestamp);
}

export function locationBuckets(comments: CommentNode[]) {
  const buckets = new Map<string, number>();
  for (const comment of comments) {
    const key = cleanIpLocation(comment.normalized.ip_location);
    buckets.set(key, (buckets.get(key) || 0) + 1);
  }
  return [...buckets.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "zh-CN"));
}

export function topAuthors(comments: CommentNode[]) {
  const buckets = new Map<string, { name: string; mid: string; count: number; likes: number; avatar?: string }>();
  for (const comment of comments) {
    const normalized = comment.normalized;
    const key = normalized.mid || normalized.user?.uname || "unknown";
    const current = buckets.get(key) || {
      name: normalized.user?.uname || "未命名用户",
      mid: normalized.mid,
      count: 0,
      likes: 0,
      avatar: normalized.user?.avatar,
    };
    current.count += 1;
    current.likes += normalized.like || 0;
    buckets.set(key, current);
  }
  return [...buckets.values()].sort((a, b) => b.count - a.count || b.likes - a.likes);
}

export function topLiked(comments: CommentNode[]) {
  return [...comments].sort((a, b) => (b.normalized.like || 0) - (a.normalized.like || 0)).slice(0, 8);
}

export function getMaxLike(comments: CommentNode[]) {
  return Math.max(1, ...comments.map((comment) => comment.normalized.like || 0));
}

export function flattenThread(comment: CommentNode): NormalizedComment[] {
  return [comment.normalized, ...(comment.replies || []).map((reply) => reply.normalized)];
}
