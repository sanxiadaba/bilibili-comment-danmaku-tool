import {
  AlertTriangle,
  ChevronRight,
  Database,
  Heart,
  LinkIcon,
  ListTree,
  MessageCircle,
  FolderOpen,
  PlayCircle,
  PlusCircle,
  RefreshCcw,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import { fetchVideos, parseVideo } from "../api/client";
import { ProgressBanner } from "../components/common";
import { InfoRow } from "../components/common";
import { StatTile } from "../components/ui/StatTile";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { cn, formatFullDateTime, formatNumber, normalizeImageUrl } from "../lib/utils";
import type { VideoSummary } from "../types";
export function VideoLibraryPage() {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isParsing, setIsParsing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [duplicateVideo, setDuplicateVideo] = useState<VideoSummary | null>(null);
  const [pendingParseTarget, setPendingParseTarget] = useState("");
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

    const bvid = extractBvid(target);
    const existingVideo = bvid ? videos.find((video) => video.bvid.toLowerCase() === bvid.toLowerCase()) : undefined;
    if (existingVideo) {
      setDuplicateVideo(existingVideo);
      setPendingParseTarget(target);
      setError("");
      setMessage("");
      return;
    }

    await runParse(target);
  }

  async function runParse(target: string) {
    setIsParsing(true);
    setDuplicateVideo(null);
    setPendingParseTarget("");
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

  function openVideo(video: VideoSummary) {
    window.history.pushState({}, "", `/video/${video.bvid}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
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
              Bilibili 评论弹幕管理
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
                  onChange={(event) => {
                    setUrl(event.target.value);
                    setDuplicateVideo(null);
                    setPendingParseTarget("");
                  }}
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
          {duplicateVideo && (
            <div className="mt-4 grid gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-ink">
              <div className="flex min-w-0 items-start gap-2">
                <AlertTriangle className="mt-0.5 shrink-0 text-amber-600" size={17} aria-hidden="true" />
                <div className="min-w-0">
                  <div className="font-medium text-amber-900">该视频已在本地档案中</div>
                  <div className="mt-1 line-clamp-2 text-amber-800">{duplicateVideo.title}</div>
                  <div className="mt-1 text-xs text-amber-700">
                    {duplicateVideo.bvid} · 档案 {formatNumber(duplicateVideo.flat_total_count)} · 弹幕{" "}
                    {formatNumber(duplicateVideo.danmaku_count)}
                  </div>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 transition hover:border-amber-500"
                  type="button"
                  onClick={() => openVideo(duplicateVideo)}
                >
                  <FolderOpen size={16} aria-hidden="true" />
                  打开已有档案
                </button>
                <button
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-3 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
                  type="button"
                  disabled={isParsing}
                  onClick={() => void runParse(pendingParseTarget)}
                >
                  <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
                  重新抓取
                </button>
              </div>
            </div>
          )}
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
                <InfoRow label="Cookie" value="data/cookie.txt" />
                <InfoRow label="数据库" value="data/comments.db" />
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

function extractBvid(value: string) {
  return value.trim().match(/BV[0-9A-Za-z]{10}/)?.[0] || "";
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
