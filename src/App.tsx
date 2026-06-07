import {
  AlertTriangle,
  BarChart3,
  ChevronRight,
  Clock3,
  Database,
  Download,
  ExternalLink,
  Eye,
  Filter,
  Heart,
  ListTree,
  LinkIcon,
  MapPin,
  MessageCircle,
  PlayCircle,
  PlusCircle,
  RefreshCcw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  ThumbsUp,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Avatar } from "./components/ui/Avatar";
import { Segmented } from "./components/ui/Segmented";
import { StatTile } from "./components/ui/StatTile";
import {
  cleanIpLocation,
  cn,
  filterComments,
  flattenThread,
  formatDateTime,
  formatFullDateTime,
  formatNumber,
  getCommentAuthor,
  getCommentAvatar,
  getCommentPictures,
  getCommentText,
  getCommentTextParts,
  getMaxLike,
  hourlyBuckets,
  locationBuckets,
  normalizeImageUrl,
  sortComments,
  topAuthors,
  topLiked,
} from "./lib/utils";
import type {
  CommentData,
  CommentNode,
  DanmakuData,
  DanmakuItem,
  LevelFilter,
  ParseVideoResponse,
  ProgressState,
  SortMode,
  VideoListResponse,
  VideoSummary,
} from "./types";

const sortLabels: Record<SortMode, string> = {
  time_asc: "时间升序",
  time_desc: "时间降序",
  like_desc: "点赞优先",
  reply_desc: "回复优先",
};

type DanmakuSortMode = "progress_asc" | "progress_desc" | "time_desc" | "content_asc";
type DanmakuModeFilter = "all" | "scroll" | "top" | "bottom" | "other";

const danmakuSortLabels: Record<DanmakuSortMode, string> = {
  progress_asc: "视频时间升序",
  progress_desc: "视频时间降序",
  time_desc: "发送时间最新",
  content_asc: "内容 A-Z",
};

const danmakuModeLabels: Record<DanmakuModeFilter, string> = {
  all: "全部",
  scroll: "滚动",
  top: "顶部",
  bottom: "底部",
  other: "其他",
};

async function fetchCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/comments?${query.toString()}`, { cache: "no-store" });
  return parseCommentResponse(response);
}

async function fetchVideos() {
  const response = await fetch(`/api/videos?ts=${Date.now()}`, { cache: "no-store" });
  return parseJsonResponse<VideoListResponse>(response);
}

async function fetchDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/danmaku?${query.toString()}`, { cache: "no-store" });
  return parseJsonResponse<DanmakuData>(response);
}

async function refreshDanmakuData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/danmaku/refresh?${query.toString()}`, {
    cache: "no-store",
    method: "POST",
  });
  return parseJsonResponse<DanmakuData>(response);
}

async function parseVideo(url: string, delay: number) {
  const response = await fetch(`/api/videos/parse?ts=${Date.now()}`, {
    cache: "no-store",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, delay }),
  });
  return parseJsonResponse<ParseVideoResponse>(response);
}

async function refreshCommentData(bvid?: string) {
  const query = new URLSearchParams({ ts: String(Date.now()) });
  if (bvid) query.set("bvid", bvid);
  const response = await fetch(`/api/refresh?${query.toString()}`, {
    cache: "no-store",
    method: "POST",
  });
  return parseCommentResponse(response);
}

async function fetchProgress() {
  const response = await fetch(`/api/progress?ts=${Date.now()}`, { cache: "no-store" });
  return parseJsonResponse<ProgressState>(response);
}

async function parseCommentResponse(response: Response) {
  return parseJsonResponse<CommentData>(response);
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

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function App() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const syncPath = () => setPath(window.location.pathname);
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);

  const danmakuMatch = path.match(/^\/danmaku\/(BV[0-9A-Za-z]{10})/);
  if (danmakuMatch) {
    return <DanmakuPage bvid={danmakuMatch[1]} />;
  }

  const detailMatch = path.match(/^\/video\/(BV[0-9A-Za-z]{10})/);
  if (detailMatch) {
    return <VideoDetailPage bvid={detailMatch[1]} />;
  }

  return <VideoLibraryPage />;
}

function useProgressPolling(enabled: boolean, kind?: string) {
  const [progress, setProgress] = useState<ProgressState | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const payload = await fetchProgress();
        if (stopped) return;
        if (!kind || payload.kind === kind || payload.active) {
          setProgress(payload);
        }
      } catch {
        // Progress is best-effort; the main request still owns the final result.
      }
      if (!stopped) {
        timer = window.setTimeout(tick, 900);
      }
    };

    void tick();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [enabled, kind]);

  return progress;
}

function VideoLibraryPage() {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isParsing, setIsParsing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const parseProgress = useProgressPolling(isParsing, "parse");
  const [parseDelay, setParseDelay] = useState(() => {
    const saved = window.localStorage.getItem("bilibili-comment-delay");
    return saved ? Number(saved) || 0.35 : 0.35;
  });

  const loadVideos = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const payload = await fetchVideos();
      setVideos(payload.videos);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadVideos();
  }, [loadVideos]);

  const filteredVideos = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return videos;
    return videos.filter((video) => {
      return (
        video.title.toLowerCase().includes(needle) ||
        video.bvid.toLowerCase().includes(needle) ||
        (video.owner_name || "").toLowerCase().includes(needle)
      );
    });
  }, [query, videos]);

  const totals = useMemo(() => {
    return videos.reduce(
      (acc, video) => {
        acc.comments += video.flat_total_count || 0;
        acc.active += video.active_comment_count || 0;
        acc.deleted += video.deleted_comment_count || 0;
        acc.likes += video.comment_like_count || 0;
        acc.danmaku += video.danmaku_count || 0;
        return acc;
      },
      { comments: 0, active: 0, deleted: 0, likes: 0, danmaku: 0 },
    );
  }, [videos]);

  async function submitParse(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = url.trim();
    if (!target) {
      setError("请输入 Bilibili 视频链接或 BV 号");
      return;
    }

    setIsParsing(true);
    setError("");
    setMessage("正在解析并抓取评论，评论较多时可能需要几十秒");
    try {
      window.localStorage.setItem("bilibili-comment-delay", String(parseDelay));
      const payload = await parseVideo(target, parseDelay);
      setMessage(
        `解析完成：本次抓到 ${payload.scraped_count} 条评论和 ${payload.danmaku_count ?? 0} 条弹幕，档案共 ${
          payload.after_count
        } 条，未返回 ${
          payload.deleted_count ?? 0
        } 条`,
      );
      window.history.pushState({}, "", `/video/${payload.bvid}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsParsing(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f4f7fb] text-ink">
      <section className="border-b border-line bg-white">
        <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span className="inline-flex items-center gap-1">
                <Database size={15} aria-hidden="true" />
                评论视频库
              </span>
              <span>{videos.length} 个视频</span>
              <span>{formatNumber(totals.comments)} 条评论档案</span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal text-ink lg:text-3xl">
              Bilibili 评论管理
            </h1>
          </div>
          <div className="flex items-center gap-2 self-center">
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              type="button"
              onClick={loadVideos}
              disabled={isLoading}
            >
              <RefreshCcw className={cn(isLoading && "animate-spin")} size={16} aria-hidden="true" />
              刷新列表
            </button>
            <button
              className={cn(
                "inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium transition",
                showSettings ? "border-bilibili text-bilibili" : "text-muted hover:border-ink hover:text-ink",
              )}
              type="button"
              onClick={() => setShowSettings((value) => !value)}
            >
              <Settings size={16} aria-hidden="true" />
              设置
            </button>
          </div>
        </div>
      </section>

      {error && (
        <section className="border-b border-red-100 bg-red-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-red-700 lg:px-6">{error}</div>
        </section>
      )}

      {message && !error && (
        <section className="border-b border-cyan-100 bg-cyan-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-cyan-700 lg:px-6">{message}</div>
        </section>
      )}

      {isParsing && <ProgressBanner progress={parseProgress} fallback="正在抓取评论和弹幕" />}

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-5 lg:px-6">
        <StatTile icon={PlayCircle} label="视频数量" value={videos.length} tone="pink" />
        <StatTile icon={MessageCircle} label="评论档案" value={totals.comments} tone="cyan" />
        <StatTile icon={AlertTriangle} label="仍可见 / 未返回" value={`${totals.active} / ${totals.deleted}`} tone="mint" />
        <StatTile icon={Sparkles} label="弹幕档案" value={totals.danmaku} tone="amber" />
        <StatTile icon={Heart} label="评论点赞" value={totals.likes} tone="amber" />
      </section>

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 pb-6 lg:grid-cols-[420px_minmax(0,1fr)] lg:px-6">
        <aside className="self-start rounded-md border border-line bg-white p-4 shadow-soft">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <PlusCircle size={18} aria-hidden="true" />
            解析新视频
          </h2>
          <form className="mt-4 grid gap-3" onSubmit={submitParse}>
            <label className="grid gap-2 text-sm text-muted">
              视频链接或 BV 号
              <span className="flex h-11 min-w-0 items-center gap-2 rounded-md border border-line px-3 focus-within:border-bilibili focus-within:ring-2 focus-within:ring-pink-100">
                <LinkIcon size={16} aria-hidden="true" />
                <input
                  className="min-w-0 flex-1 bg-transparent text-ink outline-none"
                  placeholder="https://www.bilibili.com/video/BV..."
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                />
              </span>
            </label>
            <button
              className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
              type="submit"
              disabled={isParsing}
            >
              <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
              {isParsing ? "解析中" : "解析视频"}
            </button>
          </form>
          {showSettings && (
            <div className="mt-4 grid gap-3 border-t border-line pt-4">
              <label className="grid gap-2 text-sm text-muted">
                抓取延迟
                <span className="flex h-10 items-center gap-3 rounded-md border border-line px-3">
                  <input
                    className="min-w-0 flex-1 accent-bilibili"
                    max={2}
                    min={0}
                    step={0.05}
                    type="range"
                    value={parseDelay}
                    onChange={(event) => setParseDelay(Number(event.target.value))}
                  />
                  <span className="w-14 text-right font-medium text-ink">{parseDelay.toFixed(2)}s</span>
                </span>
              </label>
              <div className="grid gap-2 text-sm">
                <InfoRow label="Cookie" value="cookie.txt" />
                <InfoRow label="数据库" value="comments.db" />
              </div>
            </div>
          )}
        </aside>

        <section className="min-w-0 rounded-md border border-line bg-white shadow-soft">
          <div className="border-b border-line p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <ListTree size={18} aria-hidden="true" />
                视频列表
              </h2>
              <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
                <Search size={16} aria-hidden="true" />
                <input
                  className="min-w-0 bg-transparent text-ink outline-none"
                  placeholder="搜索标题、UP 或 BV"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
          </div>

          <div className="grid gap-3 p-4">
            {isLoading && <div className="p-6 text-center text-sm text-muted">正在载入视频库</div>}
            {!isLoading &&
              filteredVideos.map((video) => (
                <VideoCard key={video.bvid} video={video} />
              ))}
            {!isLoading && filteredVideos.length === 0 && (
              <div className="p-6 text-center text-sm text-muted">暂无匹配的视频</div>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

function VideoCard({ video }: { video: VideoSummary }) {
  return (
    <article className="grid gap-3 rounded-md border border-line bg-[#fbfcfe] p-3 text-left transition hover:border-bilibili hover:bg-white md:grid-cols-[180px_minmax(0,1fr)_auto]">
      <div className="relative aspect-video overflow-hidden rounded-md bg-slate-100">
        {video.pic && (
          <img
            className="h-full w-full object-cover"
            src={normalizeImageUrl(video.pic)}
            alt={video.title}
            referrerPolicy="no-referrer"
          />
        )}
        <span className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs font-medium text-white">
          {video.bvid}
        </span>
      </div>
      <div className="min-w-0 self-center">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>{video.owner_name || "UP主"}</span>
          <span>{formatFullDateTime(video.fetched_at)}</span>
        </div>
        <h3 className="mt-2 line-clamp-2 text-base font-semibold leading-6 text-ink">{video.title}</h3>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>档案 {formatNumber(video.flat_total_count)}</span>
          <span>弹幕 {formatNumber(video.danmaku_count)}</span>
          <span>可见 {formatNumber(video.active_comment_count)}</span>
          <span>未返回 {formatNumber(video.deleted_comment_count)}</span>
          <span>点赞 {formatNumber(video.comment_like_count)}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 self-center md:flex-col md:items-stretch">
        <a
          className="inline-flex h-9 items-center justify-center gap-1 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
          href={`/video/${video.bvid}`}
        >
          评论
          <ChevronRight size={15} aria-hidden="true" />
        </a>
        <a
          className="inline-flex h-9 items-center justify-center gap-1 rounded-md bg-ink px-3 text-sm font-medium text-white transition hover:bg-[#26344f]"
          href={`/danmaku/${video.bvid}`}
        >
          弹幕
          <Sparkles size={15} aria-hidden="true" />
        </a>
      </div>
    </article>
  );
}

function VideoDetailPage({ bvid }: { bvid?: string }) {
  const [data, setData] = useState<CommentData | null>(null);
  const [error, setError] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState("");
  const [refreshMessage, setRefreshMessage] = useState("");
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("time_asc");
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
  const [location, setLocation] = useState("all");
  const [minLikes, setMinLikes] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const commentProgress = useProgressPolling(isRefreshing, "comments");

  const applyPayload = useCallback((payload: CommentData) => {
    setData(payload);
    setSelectedId((current) => {
      const currentExists = payload.flat_comments.some((comment) => comment.normalized.rpid === current);
      return currentExists ? current : payload.flat_comments[0]?.normalized.rpid || "";
    });
    setLastLoadedAt(new Date().toISOString());
  }, []);

  const refreshComments = useCallback(async () => {
    setIsRefreshing(true);
    setError("");
    setRefreshMessage("正在重新抓取评论，评论较多时可能需要几十秒");
    try {
      const payload = await refreshCommentData(data?.metadata.bvid || bvid);
      applyPayload(payload);
      const added = payload.refresh?.added_count ?? 0;
      const after = payload.refresh?.after_count ?? payload.metadata.flat_total_count;
      const active = payload.refresh?.active_count ?? payload.metadata.active_comment_count ?? after;
      const deleted = payload.refresh?.deleted_count ?? payload.metadata.deleted_comment_count ?? 0;
      if (payload.refresh?.warning) {
        setRefreshMessage(`${payload.refresh.warning} 当前共 ${after} 条。`);
      } else {
        setRefreshMessage(
          added > 0
            ? `已新增 ${added} 条评论，档案共 ${after} 条，仍可见 ${active} 条，未返回 ${deleted} 条`
            : `已刷新，暂无新增评论，档案共 ${after} 条，仍可见 ${active} 条，未返回 ${deleted} 条`,
        );
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setRefreshMessage("");
    } finally {
      setIsRefreshing(false);
    }
  }, [applyPayload, bvid, data?.metadata.bvid]);

  useEffect(() => {
    let mounted = true;
    fetchCommentData(bvid)
      .then((payload) => {
        if (!mounted) return;
        applyPayload(payload);
        setError("");
        setRefreshMessage("");
      })
      .catch((reason: unknown) => {
        if (!mounted) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      mounted = false;
    };
  }, [applyPayload, bvid]);

  const allComments = data?.flat_comments || [];
  const topLevelComments = data?.comments || [];

  const locations = useMemo(() => locationBuckets(allComments), [allComments]);
  const filteredComments = useMemo(
    () => sortComments(filterComments(allComments, query, levelFilter, location, minLikes), sortMode),
    [allComments, query, levelFilter, location, minLikes, sortMode],
  );
  const hourly = useMemo(() => hourlyBuckets(allComments), [allComments]);
  const filteredHourly = useMemo(() => hourlyBuckets(filteredComments), [filteredComments]);
  const authors = useMemo(() => topAuthors(allComments).slice(0, 6), [allComments]);
  const likedComments = useMemo(() => topLiked(allComments), [allComments]);
  const maxLike = useMemo(() => getMaxLike(allComments), [allComments]);

  const idToComment = useMemo(() => {
    const map = new Map<string, CommentNode>();
    allComments.forEach((comment) => map.set(comment.normalized.rpid, comment));
    return map;
  }, [allComments]);

  const idToThread = useMemo(() => {
    const map = new Map<string, CommentNode>();
    topLevelComments.forEach((comment) => map.set(comment.normalized.rpid, comment));
    return map;
  }, [topLevelComments]);

  const selectedComment =
    (selectedId && idToComment.get(selectedId)) || filteredComments[0] || allComments[0] || null;
  const selectedThread =
    selectedComment?.normalized.level === 1
      ? idToThread.get(selectedComment.normalized.rpid)
      : idToThread.get(selectedComment?.normalized.root || "");

  const topLocation = locations[0];
  const peakHour = [...hourly].sort((a, b) => b.count - a.count)[0];
  const totalLikes = allComments.reduce((sum, comment) => sum + (comment.normalized.like || 0), 0);
  const activeThreadItems = selectedThread ? flattenThread(selectedThread) : [];
  function resetFilters() {
    setQuery("");
    setSortMode("time_asc");
    setLevelFilter("all");
    setLocation("all");
    setMinLikes(0);
  }

  function exportFiltered() {
    const header = [
      "level",
      "rpid",
      "root",
      "parent",
      "ctime",
      "time_iso",
      "like",
      "rcount",
      "ip_location",
      "mid",
      "uname",
      "message",
    ];
    const rows = filteredComments.map((comment) => {
      const item = comment.normalized;
      return [
        item.level,
        item.rpid,
        item.root,
        item.parent,
        item.ctime,
        item.time_iso,
        item.like,
        item.rcount,
        item.ip_location,
        item.mid,
        item.user?.uname,
        item.message,
      ];
    });
    const csv = [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `filtered-comments-${data?.metadata.bvid || "bilibili"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (error && !data) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#f4f7fb] p-6">
        <div className="w-full max-w-lg rounded-md border border-line bg-white p-6 shadow-soft">
          <div className="flex items-center gap-3 text-red-600">
            <RefreshCcw size={20} aria-hidden="true" />
            <h1 className="text-lg font-semibold">数据加载失败</h1>
          </div>
          <p className="mt-3 text-sm text-muted">{error}</p>
          <button
            className="mt-5 inline-flex h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f]"
            type="button"
            onClick={refreshComments}
          >
            <RefreshCcw className={cn(isRefreshing && "animate-spin")} size={16} aria-hidden="true" />
            {isRefreshing ? "重新抓取中" : "重试"}
          </button>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#f4f7fb]">
        <div className="flex items-center gap-3 rounded-md border border-line bg-white px-5 py-4 text-sm text-muted shadow-soft">
          <RefreshCcw className="animate-spin" size={18} aria-hidden="true" />
          正在载入评论数据
        </div>
      </main>
    );
  }

  const activeCount = data.metadata.active_comment_count ?? data.metadata.flat_total_count;
  const deletedCount = data.metadata.deleted_comment_count ?? 0;

  return (
    <main className="min-h-screen bg-[#f4f7fb] text-ink">
      <section className="border-b border-line bg-white">
        <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-4 lg:grid-cols-[280px_minmax(0,1fr)_auto] lg:px-6">
          <div className="relative aspect-video overflow-hidden rounded-md bg-slate-100">
            {data.video_raw.pic && (
              <img
                className="h-full w-full object-cover"
                src={normalizeImageUrl(data.video_raw.pic)}
                alt={data.metadata.title}
                referrerPolicy="no-referrer"
              />
            )}
            <div className="absolute bottom-2 left-2 rounded bg-black/68 px-2 py-1 text-xs font-medium text-white">
              {data.metadata.bvid}
            </div>
          </div>
          <div className="min-w-0 self-center">
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span className="inline-flex items-center gap-1">
                <Sparkles size={15} aria-hidden="true" />
                Bilibili 评论可视化
              </span>
              <span>{data.video_raw.owner?.name || "UP主"}</span>
              <span>{formatFullDateTime(data.metadata.fetched_at)}</span>
              {lastLoadedAt && <span>检测 {formatFullDateTime(lastLoadedAt)}</span>}
            </div>
            <h1 className="mt-2 break-words text-2xl font-semibold tracking-normal text-ink lg:text-3xl">
              {data.metadata.title}
            </h1>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-muted">
              <Metric icon={Eye} label="播放" value={data.video_raw.stat?.view} />
              <Metric icon={MessageCircle} label="评论" value={data.metadata.flat_total_count} />
              <Metric icon={ThumbsUp} label="视频点赞" value={data.video_raw.stat?.like} />
              <Metric icon={Heart} label="评论点赞" value={totalLikes} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 self-center lg:flex-col lg:items-stretch">
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              href="/"
            >
              <Database size={16} aria-hidden="true" />
              视频库
            </a>
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              href={`/danmaku/${data.metadata.bvid}`}
            >
              <Sparkles size={16} aria-hidden="true" />
              弹幕页
            </a>
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-70"
              type="button"
              onClick={refreshComments}
              disabled={isRefreshing}
            >
              <RefreshCcw className={cn(isRefreshing && "animate-spin")} size={16} aria-hidden="true" />
              {isRefreshing ? "重新抓取中" : "刷新评论"}
            </button>
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f]"
              href={data.metadata.source_url}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLink size={16} aria-hidden="true" />
              打开视频
            </a>
          </div>
        </div>
      </section>

      {error && (
        <section className="border-b border-red-100 bg-red-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-red-700 lg:px-6">
            刷新失败：{error}
          </div>
        </section>
      )}

      {refreshMessage && !error && (
        <section className="border-b border-cyan-100 bg-cyan-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-cyan-700 lg:px-6">
            {refreshMessage}
          </div>
        </section>
      )}

      {isRefreshing && <ProgressBanner progress={commentProgress} fallback="正在重新抓取评论" />}

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-4 lg:px-6">
        <StatTile icon={MessageCircle} label="评论档案" value={data.metadata.flat_total_count} tone="pink" />
        <StatTile icon={AlertTriangle} label="仍可见 / 未返回" value={`${activeCount} / ${deletedCount}`} tone="cyan" />
        <StatTile icon={ListTree} label="一级评论 / 楼中楼" value={`${data.metadata.top_level_count} / ${data.metadata.nested_reply_count}`} tone="mint" />
        <StatTile icon={Clock3} label="评论峰值时段" value={peakHour?.label || "-"} tone="mint" />
      </section>

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 pb-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:px-6 xl:grid-cols-[340px_minmax(420px,560px)_340px] xl:justify-center 2xl:grid-cols-[360px_minmax(460px,620px)_360px]">
        <aside className="flex max-h-[calc(100vh-2rem)] min-w-0 flex-col self-start overflow-hidden rounded-md border border-line bg-white shadow-soft lg:sticky lg:top-4">
          <div className="border-b border-line p-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={17} />
              <input
                className="h-10 w-full rounded-md border border-line bg-white pl-10 pr-3 text-sm outline-none transition focus:border-bilibili focus:ring-2 focus:ring-pink-100"
                placeholder="搜索评论、用户或 rpid"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Segmented
                ariaLabel="评论层级"
                value={levelFilter}
                options={[
                  { label: "全部", value: "all" },
                  { label: "一级", value: "top" },
                  { label: "回复", value: "reply" },
                  { label: "UP主", value: "owner" },
                ]}
                onChange={setLevelFilter}
              />
              <button
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-muted transition hover:border-ink hover:text-ink"
                type="button"
                onClick={resetFilters}
              >
                <RefreshCcw size={15} aria-hidden="true" />
                重置
              </button>
              <button
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-muted transition hover:border-ink hover:text-ink"
                type="button"
                onClick={exportFiltered}
              >
                <Download size={15} aria-hidden="true" />
                导出
              </button>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
                <SlidersHorizontal size={15} aria-hidden="true" />
                <select
                  className="min-w-0 flex-1 truncate bg-transparent text-ink outline-none"
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value as SortMode)}
                >
                  {Object.entries(sortLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
                <MapPin size={15} aria-hidden="true" />
                <select
                  className="min-w-0 flex-1 truncate bg-transparent text-ink outline-none"
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                >
                  <option value="all">全部属地</option>
                  {locations.map((item) => (
                    <option key={item.label} value={item.label}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="mt-3 block text-sm text-muted">
              <span className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-2">
                  <ThumbsUp size={15} aria-hidden="true" />
                  最低点赞
                </span>
                <span className="font-medium text-ink">{minLikes}</span>
              </span>
              <input
                className="w-full accent-bilibili"
                max={maxLike}
                min={0}
                type="range"
                value={minLikes}
                onChange={(event) => setMinLikes(Number(event.target.value))}
              />
            </label>
          </div>

          <div className="flex items-center justify-between border-b border-line px-4 py-3 text-sm">
            <span className="inline-flex items-center gap-2 font-medium text-ink">
              <Filter size={16} aria-hidden="true" />
              匹配评论
            </span>
            <span className="text-muted">{formatNumber(filteredComments.length)}</span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {filteredComments.map((comment) => (
              <CommentRow
                active={selectedComment?.normalized.rpid === comment.normalized.rpid}
                comment={comment}
                key={comment.normalized.rpid}
                onSelect={() => setSelectedId(comment.normalized.rpid)}
              />
            ))}
            {filteredComments.length === 0 && (
              <div className="p-6 text-center text-sm text-muted">没有匹配的评论</div>
            )}
          </div>
        </aside>

        <section className="grid min-w-0 gap-4">
          <Panel
            icon={BarChart3}
            title="时间分布"
            action={`${formatNumber(filteredComments.length)} / ${formatNumber(allComments.length)}`}
          >
            <TimeChart allBuckets={hourly} filteredBuckets={filteredHourly} />
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel icon={MapPin} title="IP 属地">
              <LocationChart locations={locations.slice(0, 10)} total={allComments.length} />
            </Panel>
            <Panel icon={Users} title="活跃用户">
              <AuthorList authors={authors} />
            </Panel>
          </div>

          <Panel icon={ThumbsUp} title="点赞排行">
            <div className="grid gap-2 md:grid-cols-2">
              {likedComments.map((comment) => (
                <button
                  className={cn(
                    "min-h-24 rounded-md border border-line bg-[#fbfcfe] p-3 text-left transition hover:border-bilibili hover:bg-white",
                    selectedComment?.normalized.rpid === comment.normalized.rpid && "border-bilibili bg-pink-50",
                    comment.normalized.is_deleted && "border-red-100 bg-red-50/50",
                  )}
                  key={comment.normalized.rpid}
                  type="button"
                  onClick={() => setSelectedId(comment.normalized.rpid)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <Avatar name={getCommentAuthor(comment)} size="sm" src={getCommentAvatar(comment)} />
                      <span className="truncate text-sm font-medium text-ink">{getCommentAuthor(comment)}</span>
                    </div>
                    <span className="inline-flex items-center gap-1 text-sm font-semibold text-bilibili">
                      <ThumbsUp size={14} aria-hidden="true" />
                      {comment.normalized.like || 0}
                    </span>
                  </div>
                  {comment.normalized.is_deleted && <DeletedBadge className="mt-2" />}
                  <CommentText className="mt-2 line-clamp-2 text-sm leading-6 text-[#344158]" comment={comment} />
                  <CommentImages comment={comment} compact />
                </button>
              ))}
            </div>
          </Panel>
        </section>

        <aside className="min-w-0 overflow-hidden rounded-md border border-line bg-white shadow-soft lg:col-span-2 lg:min-h-[720px] xl:col-span-1">
          {selectedComment ? (
            <CommentDetail
              comment={selectedComment}
              threadItems={activeThreadItems}
              onSelect={(id) => setSelectedId(id)}
            />
          ) : (
            <div className="p-6 text-sm text-muted">暂无选中评论</div>
          )}
        </aside>
      </section>
    </main>
  );
}

function DanmakuPage({ bvid }: { bvid?: string }) {
  const [danmaku, setDanmaku] = useState<DanmakuData | null>(null);
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<DanmakuSortMode>("progress_asc");
  const [modeFilter, setModeFilter] = useState<DanmakuModeFilter>("all");
  const [progressRange, setProgressRange] = useState(100);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const danmakuProgress = useProgressPolling(isRefreshing, "danmaku");

  const applyDanmakuPayload = useCallback((payload: DanmakuData) => {
    setDanmaku(payload);
    setSelectedId((current) => {
      const currentExists = payload.items.some((item) => item.dmid === current);
      return currentExists ? current : payload.items[0]?.dmid || "";
    });
  }, []);

  const loadDanmaku = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const payload = await fetchDanmakuData(bvid);
      applyDanmakuPayload(payload);
      setMessage("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsLoading(false);
    }
  }, [applyDanmakuPayload, bvid]);

  useEffect(() => {
    void loadDanmaku();
  }, [loadDanmaku]);

  const allItems = danmaku?.items || [];
  const maxProgress = Math.max(0, danmaku?.metadata.max_progress || 0);
  const progressLimit = maxProgress ? (maxProgress * progressRange) / 100 : 0;

  const filteredItems = useMemo(() => {
    const items = danmaku?.items || [];
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (modeFilter !== "all" && getDanmakuModeGroup(item.mode) !== modeFilter) return false;
      if (progressLimit > 0 && item.progress > progressLimit) return false;
      if (!needle) return true;
      return (
        item.content.toLowerCase().includes(needle) ||
        item.dmid.toLowerCase().includes(needle) ||
        String(item.color).includes(needle) ||
        colorNumberToHex(item.color).toLowerCase().includes(needle)
      );
    });
  }, [danmaku?.items, modeFilter, progressLimit, query]);

  const sortedItems = useMemo(() => sortDanmakuItems(filteredItems, sortMode), [filteredItems, sortMode]);
  const filteredBuckets = useMemo(() => buildDanmakuBuckets(filteredItems), [filteredItems]);
  const modeStats = useMemo(() => buildDanmakuModeStats(filteredItems), [filteredItems]);
  const colorStats = useMemo(() => buildDanmakuColorStats(filteredItems), [filteredItems]);
  const repeatedContent = useMemo(() => buildRepeatedDanmakuContent(filteredItems), [filteredItems]);
  const peakBucket = useMemo(() => {
    return [...filteredBuckets].sort((a, b) => b.count - a.count)[0];
  }, [filteredBuckets]);
  const selectedItem =
    (selectedId && allItems.find((item) => item.dmid === selectedId)) || sortedItems[0] || allItems[0] || null;

  useEffect(() => {
    if (!sortedItems.length) {
      setSelectedId("");
      return;
    }
    setSelectedId((current) => (sortedItems.some((item) => item.dmid === current) ? current : sortedItems[0].dmid));
  }, [sortedItems]);

  async function refreshCurrentDanmaku() {
    setIsRefreshing(true);
    setError("");
    setMessage("正在重新抓取弹幕");
    try {
      const payload = await refreshDanmakuData(danmaku?.metadata.bvid || bvid);
      applyDanmakuPayload(payload);
      setMessage(
        payload.refresh?.warning ||
          `已刷新弹幕：本次抓到 ${payload.refresh?.scraped_count ?? payload.metadata.total_count} 条，档案共 ${
            payload.metadata.total_count
          } 条`,
      );
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsRefreshing(false);
    }
  }

  function exportDanmaku() {
    if (!danmaku) return;
    const header = ["progress", "time", "dmid", "mode", "font_size", "color", "like_count", "is_up_owner", "ctime", "content"];
    const rows = sortedItems.map((item) => [
      item.progress,
      formatProgress(item.progress),
      item.dmid,
      item.mode,
      item.font_size,
      colorNumberToHex(item.color),
      item.like_count || 0,
      item.is_up_owner ? "yes" : "no",
      item.ctime,
      item.content,
    ]);
    const csv = [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `danmaku-${danmaku.metadata.bvid}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function resetDanmakuFilters() {
    setQuery("");
    setSortMode("progress_asc");
    setModeFilter("all");
    setProgressRange(100);
  }

  if (isLoading && !danmaku) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#f4f7fb]">
        <div className="flex items-center gap-3 rounded-md border border-line bg-white px-5 py-4 text-sm text-muted shadow-soft">
          <RefreshCcw className="animate-spin" size={18} aria-hidden="true" />
          正在载入弹幕数据
        </div>
      </main>
    );
  }

  const totalCount = danmaku?.metadata.total_count ?? 0;
  const fetchedAt = danmaku?.metadata.fetched_at ? formatFullDateTime(danmaku.metadata.fetched_at) : "-";

  return (
    <main className="min-h-screen bg-[#f4f7fb] text-ink">
      <section className="border-b border-line bg-white">
        <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span className="inline-flex items-center gap-1">
                <Sparkles size={15} aria-hidden="true" />
                Bilibili 弹幕档案
              </span>
              <span>{danmaku?.metadata.bvid || bvid}</span>
              <span>CID {danmaku?.metadata.cid || "-"}</span>
              <span>{fetchedAt}</span>
            </div>
            <h1 className="mt-2 break-words text-2xl font-semibold tracking-normal text-ink lg:text-3xl">
              {danmaku?.metadata.title || "弹幕数据"}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 self-center lg:flex-col lg:items-stretch">
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              href="/"
            >
              <Database size={16} aria-hidden="true" />
              视频库
            </a>
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              href={`/video/${danmaku?.metadata.bvid || bvid || ""}`}
            >
              <MessageCircle size={16} aria-hidden="true" />
              评论页
            </a>
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-70"
              type="button"
              onClick={refreshCurrentDanmaku}
              disabled={isRefreshing}
            >
              <RefreshCcw className={cn(isRefreshing && "animate-spin")} size={16} aria-hidden="true" />
              {isRefreshing ? "抓取中" : "刷新弹幕"}
            </button>
            <a
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f]"
              href={`https://www.bilibili.com/video/${danmaku?.metadata.bvid || bvid || ""}`}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLink size={16} aria-hidden="true" />
              打开视频
            </a>
          </div>
        </div>
      </section>

      {error && (
        <section className="border-b border-red-100 bg-red-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-red-700 lg:px-6">{error}</div>
        </section>
      )}

      {message && !error && (
        <section className="border-b border-cyan-100 bg-cyan-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-cyan-700 lg:px-6">{message}</div>
        </section>
      )}

      {isRefreshing && <ProgressBanner progress={danmakuProgress} fallback="正在重新抓取弹幕" />}

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-5 lg:px-6">
        <StatTile icon={Sparkles} label="弹幕总数" value={totalCount} tone="amber" />
        <StatTile icon={Filter} label="当前匹配" value={sortedItems.length} tone="cyan" />
        <StatTile icon={Clock3} label="视频覆盖" value={formatProgress(danmaku?.metadata.max_progress)} tone="mint" />
        <StatTile icon={BarChart3} label="峰值片段" value={peakBucket?.label || "-"} tone="pink" />
        <StatTile icon={Database} label="CID" value={danmaku?.metadata.cid || "-"} tone="amber" />
      </section>

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 pb-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:px-6 2xl:grid-cols-[390px_minmax(0,1fr)_360px]">
        <aside className="flex max-h-[calc(100vh-2rem)] min-w-0 flex-col self-start overflow-hidden rounded-md border border-line bg-white shadow-soft lg:sticky lg:top-4">
          <div className="border-b border-line p-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={17} />
              <input
                className="h-10 w-full rounded-md border border-line bg-white pl-10 pr-3 text-sm outline-none transition focus:border-bilibili focus:ring-2 focus:ring-pink-100"
                placeholder="搜索弹幕、dmid 或颜色"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Segmented
                ariaLabel="弹幕模式"
                value={modeFilter}
                options={[
                  { label: "全部", value: "all" },
                  { label: "滚动", value: "scroll" },
                  { label: "顶部", value: "top" },
                  { label: "底部", value: "bottom" },
                  { label: "其他", value: "other" },
                ]}
                onChange={setModeFilter}
              />
              <button
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-muted transition hover:border-ink hover:text-ink"
                type="button"
                onClick={resetDanmakuFilters}
              >
                <RefreshCcw size={15} aria-hidden="true" />
                重置
              </button>
              <button
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-muted transition hover:border-ink hover:text-ink disabled:opacity-60"
                type="button"
                onClick={exportDanmaku}
                disabled={!danmaku}
              >
                <Download size={15} aria-hidden="true" />
                导出
              </button>
            </div>

            <label className="mt-3 flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
              <SlidersHorizontal size={15} aria-hidden="true" />
              <select
                className="min-w-0 flex-1 truncate bg-transparent text-ink outline-none"
                value={sortMode}
                onChange={(event) => setSortMode(event.target.value as DanmakuSortMode)}
              >
                {Object.entries(danmakuSortLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <label className="mt-3 block text-sm text-muted">
              <span className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-2">
                  <Clock3 size={15} aria-hidden="true" />
                  视频进度范围
                </span>
                <span className="font-medium text-ink">
                  00:00 - {formatProgress(progressLimit || maxProgress)}
                </span>
              </span>
              <input
                className="w-full accent-bilibili"
                max={100}
                min={1}
                type="range"
                value={progressRange}
                onChange={(event) => setProgressRange(Number(event.target.value))}
              />
            </label>
          </div>

          <div className="flex items-center justify-between border-b border-line px-4 py-3 text-sm">
            <span className="inline-flex items-center gap-2 font-medium text-ink">
              <Sparkles size={16} aria-hidden="true" />
              匹配弹幕
            </span>
            <span className="text-muted">{formatNumber(sortedItems.length)}</span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {sortedItems.map((item) => (
              <DanmakuListRow
                active={selectedItem?.dmid === item.dmid}
                item={item}
                key={item.dmid}
                onSelect={() => setSelectedId(item.dmid)}
              />
            ))}
            {sortedItems.length === 0 && (
              <div className="p-6 text-center text-sm text-muted">没有匹配的弹幕</div>
            )}
          </div>
        </aside>

        <section className="grid min-w-0 gap-4">
          <Panel icon={BarChart3} title="视频时间分布" action={`${formatNumber(sortedItems.length)} / ${formatNumber(totalCount)}`}>
            <DanmakuTimelineChart allBuckets={danmaku?.buckets || []} filteredBuckets={filteredBuckets} />
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel icon={Sparkles} title="模式分布">
              <DanmakuModeChart stats={modeStats} total={filteredItems.length} />
            </Panel>
            <Panel icon={Eye} title="颜色分布">
              <DanmakuColorList colors={colorStats} />
            </Panel>
          </div>

          <Panel icon={ListTree} title="高频内容">
            <RepeatedDanmakuList items={repeatedContent} onSelect={(item) => setSelectedId(item.sample.dmid)} />
          </Panel>

          <Panel icon={Sparkles} title="弹幕明细" action="全量可滚动">
            <DanmakuPanel danmaku={danmaku} items={sortedItems} compact />
          </Panel>
        </section>

        <aside className="min-w-0 overflow-hidden rounded-md border border-line bg-white shadow-soft lg:col-span-2 lg:min-h-[720px] 2xl:col-span-1">
          {selectedItem ? (
            <DanmakuDetail item={selectedItem} />
          ) : (
            <div className="p-6 text-sm text-muted">暂无选中弹幕</div>
          )}
        </aside>
      </section>
    </main>
  );
}

type MetricProps = {
  icon: typeof Eye;
  label: string;
  value?: number;
};

function Metric({ icon: Icon, label, value }: MetricProps) {
  return (
    <span className="inline-flex h-8 items-center gap-1 rounded-md border border-line bg-[#fbfcfe] px-2.5 text-sm">
      <Icon size={15} aria-hidden="true" />
      {label} {formatNumber(value)}
    </span>
  );
}

type PanelProps = {
  icon: LucideIcon;
  title: string;
  action?: string;
  children: ReactNode;
};

function Panel({ icon: Icon, title, action, children }: PanelProps) {
  return (
    <section className="min-w-0 overflow-hidden rounded-md border border-line bg-white shadow-soft">
      <div className="flex min-h-14 items-center justify-between border-b border-line px-4">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <Icon size={18} aria-hidden="true" />
          {title}
        </h2>
        {action && <span className="text-sm text-muted">{action}</span>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

type ProgressBannerProps = {
  progress: ProgressState | null;
  fallback: string;
};

function ProgressBanner({ progress, fallback }: ProgressBannerProps) {
  const logs = progress?.logs?.slice(-4) || [];
  const percent = Math.max(0, Math.min(100, Math.round(progress?.percent ?? 8)));
  const stage = progress?.stage || "准备中";
  const stats = Object.entries(progress?.stats || {}).slice(0, 4);
  return (
    <section className="border-b border-amber-100 bg-[#fff8e7]">
      <div className="mx-auto max-w-[1540px] px-4 py-3 text-sm text-[#5f4612] lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 font-semibold text-ink">
              <RefreshCcw className="animate-spin text-amber" size={16} aria-hidden="true" />
              <span>{stage}</span>
              <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-[#6b4b13]">{percent}%</span>
            </div>
            <div className="mt-1 truncate text-sm text-[#6b4b13]">{progress?.message || fallback}</div>
          </div>
          {stats.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {stats.map(([label, value]) => (
                <span className="rounded-md border border-amber-100 bg-white px-2.5 py-1 text-xs" key={label}>
                  {label} <strong className="text-ink">{value}</strong>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
          <div className="h-full rounded-full bg-amber transition-all duration-300" style={{ width: `${percent}%` }} />
        </div>

        {logs.length > 0 && (
          <div className="mt-2 grid gap-1 text-xs text-[#7a5a1a]">
            {logs.map((item, index) => (
              <div className="flex min-w-0 items-center gap-2" key={`${item}-${index}`}>
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" />
                <span className="truncate">
                {item}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

type DanmakuBucket = {
  bucket_start: number;
  label: string;
  count: number;
};

type DanmakuListRowProps = {
  item: DanmakuItem;
  active: boolean;
  onSelect: () => void;
};

function DanmakuListRow({ item, active, onSelect }: DanmakuListRowProps) {
  return (
    <button
      className={cn(
        "block w-full border-b border-line px-4 py-3 text-left transition hover:bg-[#fbfcfe]",
        active && "bg-amber-50",
      )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex h-8 w-16 shrink-0 items-center justify-center rounded bg-amber-50 text-sm font-semibold text-amber">
          {formatProgress(item.progress)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="line-clamp-2 min-w-0 flex-1 break-words text-sm font-medium leading-6 text-ink">
              {item.content}
            </div>
            {item.is_up_owner && <OwnerBadge />}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{getDanmakuModeLabel(item.mode)}</span>
            <ColorSwatch color={item.color} />
            <span className="inline-flex items-center gap-1">
              <ThumbsUp size={12} aria-hidden="true" />
              {item.like_count || 0}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

type DanmakuTimelineChartProps = {
  allBuckets: DanmakuBucket[];
  filteredBuckets: DanmakuBucket[];
};

function DanmakuTimelineChart({ allBuckets, filteredBuckets }: DanmakuTimelineChartProps) {
  const filteredByTime = new Map(filteredBuckets.map((bucket) => [bucket.bucket_start, bucket.count]));
  const max = Math.max(1, ...allBuckets.map((bucket) => bucket.count));

  if (!allBuckets.length) {
    return (
      <div className="grid min-h-44 place-items-center rounded-md border border-dashed border-line bg-[#fbfcfe] p-6 text-center text-sm text-muted">
        暂无可绘制的弹幕分布
      </div>
    );
  }

  return (
    <div className="h-72 w-full max-w-full overflow-hidden">
      <div className="flex h-60 min-w-0 items-end gap-1 border-b border-line">
        {allBuckets.map((bucket) => {
          const filteredCount = filteredByTime.get(bucket.bucket_start) || 0;
          return (
            <div className="group flex min-w-0 flex-1 flex-col items-center justify-end gap-1" key={bucket.bucket_start}>
              <div className="relative flex h-52 w-full items-end rounded-t bg-slate-100">
                <div
                  className="w-full rounded-t bg-amber/30"
                  style={{ height: `${Math.max(4, (bucket.count / max) * 100)}%` }}
                />
                <div
                  className="absolute bottom-0 w-full rounded-t bg-amber"
                  style={{ height: filteredCount ? `${Math.max(4, (filteredCount / max) * 100)}%` : 0 }}
                />
              </div>
              <span className="hidden text-[10px] text-muted group-hover:block">{bucket.count}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex min-w-0 items-center justify-between gap-3 text-xs text-muted">
        <span className="min-w-0 truncate">{allBuckets[0]?.label || "00:00"}</span>
        <span className="inline-flex shrink-0 items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded-sm bg-amber/30" />
            全部
          </span>
          <span className="inline-flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded-sm bg-amber" />
            筛选
          </span>
        </span>
        <span className="min-w-0 truncate text-right">{allBuckets.at(-1)?.label || "-"}</span>
      </div>
    </div>
  );
}

type DanmakuModeChartProps = {
  stats: Array<{ mode: DanmakuModeFilter; label: string; count: number }>;
  total: number;
};

function DanmakuModeChart({ stats, total }: DanmakuModeChartProps) {
  const max = Math.max(1, ...stats.map((item) => item.count));
  return (
    <div className="space-y-3">
      {stats.map((item) => (
        <div className="grid grid-cols-[56px_minmax(0,1fr)_48px] items-center gap-3 text-sm" key={item.mode}>
          <span className="truncate font-medium text-ink">{item.label}</span>
          <div className="h-3 overflow-hidden rounded-sm bg-slate-100">
            <div className="h-full rounded-sm bg-cyan" style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <span className="text-right text-muted">{total ? Math.round((item.count / total) * 100) : 0}%</span>
        </div>
      ))}
    </div>
  );
}

type DanmakuColorListProps = {
  colors: Array<{ color: number; label: string; count: number }>;
};

function DanmakuColorList({ colors }: DanmakuColorListProps) {
  if (!colors.length) {
    return <div className="p-6 text-center text-sm text-muted">暂无颜色数据</div>;
  }

  return (
    <div className="space-y-3">
      {colors.slice(0, 8).map((item) => (
        <div className="flex items-center justify-between gap-3" key={item.color}>
          <div className="flex min-w-0 items-center gap-3">
            <span
              className="h-6 w-6 shrink-0 rounded border border-line"
              style={{ backgroundColor: colorNumberToHex(item.color) }}
            />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-ink">{item.label}</div>
              <div className="text-xs text-muted">{formatNumber(item.count)} 条</div>
            </div>
          </div>
          <span className="rounded bg-[#fbfcfe] px-2 py-1 text-sm font-medium text-muted">
            {Math.round((item.count / Math.max(1, colors.reduce((sum, color) => sum + color.count, 0))) * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}

type RepeatedDanmakuListProps = {
  items: Array<{ content: string; count: number; sample: DanmakuItem }>;
  onSelect: (item: { content: string; count: number; sample: DanmakuItem }) => void;
};

function RepeatedDanmakuList({ items, onSelect }: RepeatedDanmakuListProps) {
  if (!items.length) {
    return <div className="p-6 text-center text-sm text-muted">暂无重复内容</div>;
  }

  return (
    <div className="grid gap-2 md:grid-cols-2">
      {items.slice(0, 8).map((item) => (
        <button
          className="min-h-20 rounded-md border border-line bg-[#fbfcfe] p-3 text-left transition hover:border-bilibili hover:bg-white"
          key={`${item.content}-${item.sample.dmid}`}
          type="button"
          onClick={() => onSelect(item)}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="line-clamp-1 min-w-0 text-sm font-semibold text-ink">{item.content}</span>
            <span className="shrink-0 rounded bg-amber-50 px-2 py-1 text-sm font-semibold text-amber">
              {formatNumber(item.count)}
            </span>
          </div>
          <div className="mt-2 text-xs text-muted">样本时间 {formatProgress(item.sample.progress)}</div>
        </button>
      ))}
    </div>
  );
}

type DanmakuDetailProps = {
  item: DanmakuItem;
};

function DanmakuDetail({ item }: DanmakuDetailProps) {
  const createdAt = item.ctime ? formatFullDateTime(new Date(item.ctime * 1000).toISOString()) : "-";
  return (
    <div>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-11 w-20 shrink-0 items-center justify-center rounded-md bg-amber-50 text-base font-semibold text-amber">
            {formatProgress(item.progress)}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="break-words text-lg font-semibold leading-7 text-ink">{item.content}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
              {item.is_up_owner && <OwnerBadge />}
              <span>{getDanmakuModeLabel(item.mode)}</span>
              <ColorSwatch color={item.color} />
              <span>字号 {item.font_size}</span>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <DetailMetric icon={Clock3} label="视频时间" value={formatProgress(item.progress)} />
          <DetailMetric icon={Sparkles} label="模式" value={getDanmakuModeLabel(item.mode)} />
          <DetailMetric icon={ThumbsUp} label="点赞" value={item.like_count || 0} />
        </div>
      </div>

      <div className="border-b border-line p-4">
        <h3 className="text-sm font-semibold text-ink">显示信息</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="颜色" value={colorNameForDanmaku(item.color)} />
          <InfoRow label="字号" value={String(item.font_size)} />
          <InfoRow label="弹幕池" value={String(item.pool)} />
          <InfoRow label="发送时间" value={createdAt} />
        </dl>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-ink">原始标识</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="dmid" value={item.dmid} />
          <InfoRow label="bvid" value={item.bvid} />
          <InfoRow label="cid" value={item.cid || "-"} />
          <InfoRow label="入库时间" value={formatFullDateTime(item.fetched_at)} />
        </dl>
      </div>
    </div>
  );
}

type DanmakuPanelProps = {
  danmaku: DanmakuData | null;
  items?: DanmakuItem[];
  compact?: boolean;
};

function DanmakuPanel({ danmaku, items: panelItems, compact = false }: DanmakuPanelProps) {
  const items = panelItems || danmaku?.items || [];
  const buckets = danmaku?.buckets || [];
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const fetchedAt = danmaku?.metadata.fetched_at ? formatFullDateTime(danmaku.metadata.fetched_at) : "";

  if (!danmaku || danmaku.metadata.total_count === 0) {
    return (
      <div className="grid min-h-44 place-items-center rounded-md border border-dashed border-line bg-[#fbfcfe] p-6 text-center text-sm text-muted">
        暂无弹幕数据，点击刷新会重新抓取当前视频的评论和弹幕。
      </div>
    );
  }

  if (compact) {
    return (
      <div className="max-h-[640px] overflow-y-auto rounded-md border border-line bg-[#fbfcfe] p-2">
        {items.map((item) => (
          <DanmakuRow item={item} key={item.dmid} />
        ))}
        {items.length === 0 && <div className="p-6 text-center text-sm text-muted">没有匹配的弹幕</div>}
      </div>
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <div className="mb-3 grid gap-2 text-sm sm:grid-cols-3">
          <DanmakuMetric label="CID" value={danmaku.metadata.cid || "-"} />
          <DanmakuMetric label="覆盖时间" value={formatProgress(danmaku.metadata.max_progress)} />
          <DanmakuMetric label="抓取时间" value={fetchedAt || "-"} />
        </div>
        <div className="h-56 w-full max-w-full overflow-hidden rounded-md border border-line bg-[#fbfcfe] p-3">
          <div className="flex h-44 min-w-0 items-end gap-1 border-b border-line">
            {buckets.map((bucket) => (
              <div
                className="group flex min-w-0 flex-1 flex-col items-center justify-end"
                key={bucket.bucket_start}
                title={`${bucket.label}：${bucket.count} 条`}
              >
                <div
                  className="w-full rounded-t bg-amber"
                  style={{ height: `${Math.max(4, (bucket.count / max) * 100)}%` }}
                />
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted">
            <span className="min-w-0 truncate">{buckets[0]?.label || "00:00"}</span>
            <span className="shrink-0">按视频进度聚合</span>
            <span className="min-w-0 truncate text-right">{buckets.at(-1)?.label || "-"}</span>
          </div>
        </div>
      </div>

      <div className="min-w-0 rounded-md border border-line bg-[#fbfcfe]">
        <div className="flex h-11 items-center justify-between border-b border-line px-3 text-sm">
          <span className="font-semibold text-ink">弹幕明细</span>
          <span className="text-muted">{formatNumber(items.length)} 条</span>
        </div>
        <div className="max-h-[640px] overflow-y-auto p-2">
          {items.map((item) => (
            <DanmakuRow item={item} key={item.dmid} />
          ))}
        </div>
      </div>
    </div>
  );
}

type DanmakuMetricProps = {
  label: string;
  value: string;
};

function DanmakuMetric({ label, value }: DanmakuMetricProps) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-[#fbfcfe] px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-ink">{value}</div>
    </div>
  );
}

type DanmakuRowProps = {
  item: DanmakuItem;
};

function DanmakuRow({ item }: DanmakuRowProps) {
  return (
    <div className="grid grid-cols-[58px_minmax(0,1fr)] gap-3 rounded-md px-2 py-2 text-sm hover:bg-white">
      <span className="inline-flex h-7 items-center justify-center rounded bg-amber-50 font-medium text-amber">
        {formatProgress(item.progress)}
      </span>
      <div className="min-w-0">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 break-words leading-7 text-[#344158]">{item.content}</div>
          {item.is_up_owner && <OwnerBadge />}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>ID {item.dmid}</span>
          <ColorSwatch color={item.color} />
          <span className="inline-flex items-center gap-1">
            <ThumbsUp size={12} aria-hidden="true" />
            {item.like_count || 0}
          </span>
        </div>
      </div>
    </div>
  );
}

type ColorSwatchProps = {
  color: number;
};

function ColorSwatch({ color }: ColorSwatchProps) {
  const label = colorNameForDanmaku(color);
  return (
    <span className="inline-flex items-center gap-1.5">
      <i
        className="h-3.5 w-3.5 rounded-sm border border-line"
        style={{ backgroundColor: colorNumberToHex(color) }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function formatProgress(seconds?: number) {
  const value = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function getBilibiliUserUrl(mid?: string) {
  return mid ? `https://space.bilibili.com/${mid}` : undefined;
}

function sortDanmakuItems(items: DanmakuItem[], sortMode: DanmakuSortMode) {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (sortMode === "progress_desc") return b.progress - a.progress || b.dmid.localeCompare(a.dmid);
    if (sortMode === "time_desc") return b.ctime - a.ctime || b.dmid.localeCompare(a.dmid);
    if (sortMode === "content_asc") return a.content.localeCompare(b.content, "zh-CN") || a.progress - b.progress;
    return a.progress - b.progress || a.dmid.localeCompare(b.dmid);
  });
  return sorted;
}

function buildDanmakuBuckets(items: DanmakuItem[]): DanmakuBucket[] {
  const buckets = new Map<number, number>();
  for (const item of items) {
    const bucketStart = Math.floor((item.progress || 0) / 10) * 10;
    buckets.set(bucketStart, (buckets.get(bucketStart) || 0) + 1);
  }
  return [...buckets.entries()]
    .map(([bucket_start, count]) => ({ bucket_start, label: formatProgress(bucket_start), count }))
    .sort((a, b) => a.bucket_start - b.bucket_start);
}

function buildDanmakuModeStats(items: DanmakuItem[]) {
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

function buildDanmakuColorStats(items: DanmakuItem[]) {
  const counts = new Map<number, number>();
  for (const item of items) {
    counts.set(item.color, (counts.get(item.color) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([color, count]) => ({ color, label: colorNameForDanmaku(color), count }))
    .sort((a, b) => b.count - a.count || a.color - b.color);
}

function buildRepeatedDanmakuContent(items: DanmakuItem[]) {
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

function getDanmakuModeGroup(mode: number): DanmakuModeFilter {
  if (mode === 1 || mode === 2 || mode === 3) return "scroll";
  if (mode === 5) return "top";
  if (mode === 4) return "bottom";
  return "other";
}

function getDanmakuModeLabel(mode: number) {
  const group = getDanmakuModeGroup(mode);
  if (group === "other") return `模式 ${mode}`;
  return danmakuModeLabels[group];
}

function colorNumberToHex(color: number) {
  const normalized = Math.max(0, Math.min(0xffffff, color || 0));
  return `#${normalized.toString(16).padStart(6, "0").toUpperCase()}`;
}

function colorNameForDanmaku(color: number) {
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

type CommentRowProps = {
  comment: CommentNode;
  active: boolean;
  onSelect: () => void;
};

function CommentRow({ comment, active, onSelect }: CommentRowProps) {
  const normalized = comment.normalized;
  const profileUrl = getBilibiliUserUrl(normalized.mid);
  return (
    <button
      className={cn(
      "block w-full border-b border-line px-4 py-3 text-left transition hover:bg-[#fbfcfe]",
      active && "bg-pink-50",
      normalized.is_deleted && "bg-red-50/45 hover:bg-red-50",
    )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex items-center gap-3">
        <Avatar
          name={getCommentAuthor(comment)}
          size="md"
          src={getCommentAvatar(comment)}
          href={profileUrl}
          onClick={(event) => event.stopPropagation()}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-ink">{getCommentAuthor(comment)}</span>
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-0.5 text-xs font-medium",
                normalized.level === 1 ? "bg-cyan-50 text-cyan" : "bg-amber-50 text-amber",
              )}
            >
              {normalized.level === 1 ? "一级" : "回复"}
            </span>
            {normalized.is_up_owner && <OwnerBadge />}
            {normalized.is_deleted && <DeletedBadge />}
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted">
            <span>{formatDateTime(normalized.time_iso)}</span>
            <span>{cleanIpLocation(normalized.ip_location)}</span>
            <span className="inline-flex items-center gap-1">
              <ThumbsUp size={12} aria-hidden="true" />
              {normalized.like || 0}
            </span>
          </div>
        </div>
      </div>
      <CommentText
        className={cn("mt-2 line-clamp-2 text-sm leading-6 text-[#344158]", normalized.is_deleted && "text-[#6b4750]")}
        comment={comment}
      />
      <CommentImages comment={comment} compact />
    </button>
  );
}

type CommentTextProps = {
  comment?: CommentNode;
  normalized?: CommentNode["normalized"];
  className?: string;
};

function CommentText({ comment, normalized, className }: CommentTextProps) {
  const data = normalized || comment?.normalized;
  if (!data) return null;
  const parts = getCommentTextParts(data);

  return (
    <p className={className}>
      {parts.map((part, index) => {
        if (part.type === "text") {
          return <span key={`${part.text}-${index}`}>{part.text}</span>;
        }

        const large = part.size && part.size > 1;
        return (
          <img
            className={cn(
              "mx-0.5 inline-block align-[-0.28em]",
              large ? "h-12 max-w-24" : "h-5 w-5",
            )}
            src={part.url}
            alt={part.text}
            title={part.title}
            loading="eager"
            referrerPolicy="no-referrer"
            key={`${part.text}-${index}`}
          />
        );
      })}
    </p>
  );
}

type CommentImagesProps = {
  comment: CommentNode;
  compact?: boolean;
};

function CommentImages({ comment, compact = false }: CommentImagesProps) {
  const pictures = getCommentPictures(comment);
  if (!pictures.length) return null;

  return (
    <div className={cn("mt-3 grid gap-2", compact ? "grid-cols-3" : "grid-cols-2")}>
      {pictures.map((picture, index) => (
        <a
          className={cn(
            "group relative block overflow-hidden rounded-md border border-line bg-slate-100 transition hover:border-bilibili",
            compact ? "aspect-square" : "aspect-[4/3]",
          )}
          href={picture.img_src}
          key={`${picture.img_src}-${index}`}
          target="_blank"
          rel="noreferrer"
        >
          <img
            className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
            src={picture.img_src}
            alt={`评论图片 ${index + 1}`}
            loading="eager"
            referrerPolicy="no-referrer"
          />
          {picture.play_gif_thumbnail && (
            <span className="absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
              GIF
            </span>
          )}
        </a>
      ))}
    </div>
  );
}

type DeletedBadgeProps = {
  className?: string;
};

function OwnerBadge() {
  return (
    <span className="inline-flex shrink-0 items-center rounded border border-bilibili/25 bg-pink-50 px-1.5 py-0.5 text-xs font-medium text-bilibili">
      UP主
    </span>
  );
}

function DeletedBadge({ className }: DeletedBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700",
        className,
      )}
      title="这条评论在最近一次刷新中没有被 Bilibili API 返回，已保留在本地档案中"
    >
      <AlertTriangle size={12} aria-hidden="true" />
      本次未返回
    </span>
  );
}

type TimeChartProps = {
  allBuckets: Array<{ label: string; count: number; timestamp: number }>;
  filteredBuckets: Array<{ label: string; count: number; timestamp: number }>;
};

function TimeChart({ allBuckets, filteredBuckets }: TimeChartProps) {
  const filteredByTime = new Map(filteredBuckets.map((bucket) => [bucket.timestamp, bucket.count]));
  const max = Math.max(1, ...allBuckets.map((bucket) => bucket.count));
  const chartWidth = Math.max(520, allBuckets.length * 16);

  if (!allBuckets.length) {
    return (
      <div className="grid min-h-56 place-items-center rounded-md border border-dashed border-line bg-[#fbfcfe] p-6 text-center text-sm text-muted">
        暂无可绘制的评论时间数据
      </div>
    );
  }

  return (
    <div className="min-w-0 w-full max-w-full">
      <div className="overflow-x-auto overflow-y-hidden pb-2">
        <div className="h-64" style={{ width: `${chartWidth}px` }}>
          <div className="flex h-56 items-end gap-1 border-b border-line">
            {allBuckets.map((bucket) => {
              const filteredCount = filteredByTime.get(bucket.timestamp) || 0;
              return (
                <div
                  className="group flex h-full min-w-3 flex-1 flex-col items-center justify-end gap-1"
                  key={bucket.timestamp}
                  title={`${bucket.label}：全部 ${bucket.count} 条，筛选 ${filteredCount} 条`}
                >
                  <div className="relative flex h-52 w-full items-end rounded-t bg-slate-100">
                    <div
                      className="w-full rounded-t bg-cyan/35"
                      style={{ height: `${Math.max(6, (bucket.count / max) * 100)}%` }}
                    />
                    <div
                      className="absolute bottom-0 w-full rounded-t bg-bilibili"
                      style={{ height: filteredCount ? `${Math.max(6, (filteredCount / max) * 100)}%` : 0 }}
                    />
                  </div>
                  <span className="hidden text-[10px] text-muted group-hover:block">{bucket.count}</span>
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex min-w-0 items-center justify-between gap-3 text-xs text-muted">
            <span className="min-w-0 truncate">{allBuckets[0]?.label}</span>
            <span className="inline-flex shrink-0 items-center gap-3">
              <span className="inline-flex items-center gap-1">
                <i className="h-2.5 w-2.5 rounded-sm bg-cyan/35" />
                全部
              </span>
              <span className="inline-flex items-center gap-1">
                <i className="h-2.5 w-2.5 rounded-sm bg-bilibili" />
                筛选
              </span>
            </span>
            <span className="min-w-0 truncate text-right">{allBuckets.at(-1)?.label}</span>
          </div>
        </div>
      </div>
      <div className="mt-1 flex justify-between gap-3 text-xs text-muted">
        <span>共 {allBuckets.length} 个时间段</span>
        <span>可横向滚动查看完整时间线</span>
      </div>
    </div>
  );
}
type LocationChartProps = {
  locations: Array<{ label: string; count: number }>;
  total: number;
};

function LocationChart({ locations, total }: LocationChartProps) {
  const max = Math.max(1, ...locations.map((item) => item.count));
  return (
    <div className="space-y-3">
      {locations.map((item) => (
        <div className="grid grid-cols-[72px_minmax(0,1fr)_44px] items-center gap-3 text-sm" key={item.label}>
          <span className="truncate font-medium text-ink">{item.label}</span>
          <div className="h-3 overflow-hidden rounded-sm bg-slate-100">
            <div className="h-full rounded-sm bg-mint" style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <span className="text-right text-muted">{Math.round((item.count / total) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

type AuthorListProps = {
  authors: Array<{ name: string; mid: string; count: number; likes: number; avatar?: string }>;
};

function AuthorList({ authors }: AuthorListProps) {
  return (
    <div className="space-y-3">
      {authors.map((author) => (
        <div className="flex items-center justify-between gap-3" key={author.mid || author.name}>
          <div className="flex min-w-0 items-center gap-3">
            <Avatar name={author.name} size="md" src={normalizeImageUrl(author.avatar)} href={getBilibiliUserUrl(author.mid)} />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-ink">{author.name}</div>
              <div className="text-xs text-muted">{author.count} 条评论</div>
            </div>
          </div>
          <span className="inline-flex items-center gap-1 rounded bg-pink-50 px-2 py-1 text-sm font-semibold text-bilibili">
            <ThumbsUp size={13} aria-hidden="true" />
            {author.likes}
          </span>
        </div>
      ))}
    </div>
  );
}

type CommentDetailProps = {
  comment: CommentNode;
  threadItems: ReturnType<typeof flattenThread>;
  onSelect: (id: string) => void;
};

function CommentDetail({ comment, threadItems, onSelect }: CommentDetailProps) {
  const normalized = comment.normalized;
  const profileUrl = getBilibiliUserUrl(normalized.mid);

  return (
    <div>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <Avatar name={getCommentAuthor(comment)} size="lg" src={getCommentAvatar(comment)} href={profileUrl} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold text-ink">{getCommentAuthor(comment)}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
              <span>UID {normalized.mid}</span>
              <span>{cleanIpLocation(normalized.ip_location)}</span>
              <span>{normalized.level === 1 ? "一级评论" : "楼中楼回复"}</span>
              {normalized.is_up_owner && <OwnerBadge />}
              {normalized.is_deleted && <DeletedBadge />}
            </div>
          </div>
        </div>

        <CommentText
          className="mt-4 whitespace-pre-wrap break-words text-base leading-7 text-[#253148]"
          comment={comment}
        />
        <CommentImages comment={comment} />

        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <DetailMetric icon={ThumbsUp} label="点赞" value={normalized.like || 0} />
          <DetailMetric icon={MessageCircle} label="回复" value={normalized.rcount || 0} />
          <DetailMetric icon={Clock3} label="时间" value={formatDateTime(normalized.time_iso)} />
        </div>
        {normalized.is_deleted && (
          <div className="mt-3 rounded-md border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
            最近一次刷新未返回这条评论，可能已被删除、折叠或接口暂未返回。最后可见：
            {formatFullDateTime(normalized.last_seen_at)}；首次未返回：
            {formatFullDateTime(normalized.missing_since)}。
          </div>
        )}
      </div>

      <div className="border-b border-line p-4">
        <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
          <ListTree size={16} aria-hidden="true" />
          当前线程
        </h3>
        <div className="mt-3 max-h-[340px] space-y-2 overflow-y-auto pr-1">
          {threadItems.map((item) => (
            <button
              className={cn(
                "w-full rounded-md border border-line bg-[#fbfcfe] p-3 text-left transition hover:border-bilibili hover:bg-white",
                item.rpid === normalized.rpid && "border-bilibili bg-pink-50",
              )}
              key={item.rpid}
              type="button"
              onClick={() => onSelect(item.rpid)}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm font-semibold text-ink">{item.user?.uname || "未命名用户"}</span>
                <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                  {item.is_up_owner && <OwnerBadge />}
                  {item.is_deleted && <DeletedBadge />}
                  {formatDateTime(item.time_iso)}
                </span>
              </div>
              <CommentText className="mt-1 line-clamp-3 text-sm leading-6 text-[#344158]" normalized={item} />
            </button>
          ))}
        </div>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-ink">原始标识</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="rpid" value={normalized.rpid} />
          <InfoRow label="root" value={normalized.root} />
          <InfoRow label="parent" value={normalized.parent} />
          <InfoRow label="ctime" value={String(normalized.ctime)} />
          <InfoRow label="完整时间" value={formatFullDateTime(normalized.time_iso)} />
          <InfoRow label="最后可见" value={formatFullDateTime(normalized.last_seen_at)} />
          <InfoRow label="首次未返回" value={formatFullDateTime(normalized.missing_since)} />
        </dl>
      </div>
    </div>
  );
}

type DetailMetricProps = {
  icon: typeof ThumbsUp;
  label: string;
  value: number | string;
};

function DetailMetric({ icon: Icon, label, value }: DetailMetricProps) {
  return (
    <div className="rounded-md border border-line bg-[#fbfcfe] p-3">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Icon size={14} aria-hidden="true" />
        {label}
      </div>
      <div className="mt-2 break-words text-sm font-semibold text-ink">{value}</div>
    </div>
  );
}

type InfoRowProps = {
  label: string;
  value: string;
};

function InfoRow({ label, value }: InfoRowProps) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 rounded bg-[#fbfcfe] px-3 py-2">
      <dt className="text-muted">{label}</dt>
      <dd className="break-all font-mono text-xs text-ink">{value}</dd>
    </div>
  );
}

export default App;
