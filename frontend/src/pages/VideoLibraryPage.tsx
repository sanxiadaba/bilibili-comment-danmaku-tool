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
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import { archiveSpaceVideos, fetchVideos, logClientEvent, parseVideo } from "../api/client";
import { ProgressBanner } from "../components/common";
import { InfoRow } from "../components/common";
import { StatTile } from "../components/ui/StatTile";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { cn, formatFullDateTime, formatNumber, normalizeImageUrl } from "../lib/utils";
import type { ProgressQueue, ProgressTask, VideoSummary } from "../types";
export function VideoLibraryPage() {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isParsing, setIsParsing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [ownerRef, setOwnerRef] = useState("");
  const [isArchivingSpace, setIsArchivingSpace] = useState(false);
  const [isSubmittingSpace, setIsSubmittingSpace] = useState(false);
  const [duplicateVideo, setDuplicateVideo] = useState<VideoSummary | null>(null);
  const [pendingParseTarget, setPendingParseTarget] = useState("");
  const parseProgress = useProgressPolling(isParsing, "parse");
  const spaceProgress = useProgressPolling(true);
  const [parseDelay, setParseDelay] = useState(() => {
    const saved = window.localStorage.getItem("bilibili-comment-delay");
    return saved ? Number(saved) || 0.35 : 0.35;
  });
  const spaceQueue = spaceProgress?.queue;
  const hasSpaceQueueWork = Boolean(spaceQueue?.active || spaceQueue?.queued?.length);
  const isTaskBusy = isParsing || hasSpaceQueueWork;

  const loadVideos = useCallback(async (options?: { quiet?: boolean }) => {
    if (!options?.quiet) {
      setIsLoading(true);
    }
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

  useEffect(() => {
    if (!isArchivingSpace || hasSpaceQueueWork) return;
    setIsArchivingSpace(false);
    void loadVideos();
  }, [hasSpaceQueueWork, isArchivingSpace, loadVideos]);

  useEffect(() => {
    if (!hasSpaceQueueWork) return;
    const timer = window.setInterval(() => {
      void loadVideos({ quiet: true });
    }, 15000);
    return () => window.clearInterval(timer);
  }, [hasSpaceQueueWork, loadVideos]);

  const ownerGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        key: string;
        name: string;
        videoCount: number;
        commentCount: number;
        danmakuCount: number;
      }
    >();

    for (const video of videos) {
      const key = ownerKey(video);
      const existing = groups.get(key);
      if (existing) {
        existing.videoCount += 1;
        existing.commentCount += video.comment_total_count || 0;
        existing.danmakuCount += video.danmaku_count || 0;
      } else {
        groups.set(key, {
          key,
          name: ownerName(video),
          videoCount: 1,
          commentCount: video.comment_total_count || 0,
          danmakuCount: video.danmaku_count || 0,
        });
      }
    }

    return Array.from(groups.values()).sort((first, second) => {
      if (second.videoCount !== first.videoCount) return second.videoCount - first.videoCount;
      if (second.commentCount !== first.commentCount) return second.commentCount - first.commentCount;
      return first.name.localeCompare(second.name, "zh-Hans-CN");
    });
  }, [videos]);

  useEffect(() => {
    if (ownerFilter === "all") return;
    if (!ownerGroups.some((group) => group.key === ownerFilter)) {
      setOwnerFilter("all");
    }
  }, [ownerFilter, ownerGroups]);

  const selectedOwnerName = ownerGroups.find((group) => group.key === ownerFilter)?.name;

  const filteredVideos = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const ownerScopedVideos =
      ownerFilter === "all" ? videos : videos.filter((video) => ownerKey(video) === ownerFilter);
    if (!needle) return ownerScopedVideos;
    return ownerScopedVideos.filter((video) => {
      return (
        video.title.toLowerCase().includes(needle) ||
        video.bvid.toLowerCase().includes(needle) ||
        (video.owner_name || "").toLowerCase().includes(needle)
      );
    });
  }, [ownerFilter, query, videos]);

  const totals = useMemo(() => {
    return videos.reduce(
      (acc, video) => {
        acc.comments += video.comment_total_count || 0;
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
      logClientEvent("client.user.parse.invalid_input", "parse submitted without video reference");
      setError("请输入 Bilibili 视频链接或 BV 号");
      return;
    }

    const bvid = extractBvid(target);
    const existingVideo = bvid ? videos.find((video) => video.bvid.toLowerCase() === bvid.toLowerCase()) : undefined;
    if (existingVideo) {
      logClientEvent("client.user.parse.duplicate_detected", "existing video detected before parse", {
        bvid: existingVideo.bvid,
        title: existingVideo.title,
      });
      setDuplicateVideo(existingVideo);
      setPendingParseTarget(target);
      setError("");
      setMessage("");
      return;
    }

    await runParse(target);
  }

  async function runParse(target: string) {
    const targetBvid = extractBvid(target);
    logClientEvent("client.user.parse.start", "user started video parse", {
      bvid: targetBvid,
      delay: parseDelay,
      source: duplicateVideo ? "duplicate_confirm" : "form",
    });
    setIsParsing(true);
    setDuplicateVideo(null);
    setPendingParseTarget("");
    setError("");
    setMessage("正在解析并抓取评论，评论较多时可能需要几十秒");
    try {
      window.localStorage.setItem("bilibili-comment-delay", String(parseDelay));
      const payload = await parseVideo(target, parseDelay);
      logClientEvent("client.user.parse.success", "video parse completed", {
        bvid: payload.bvid,
        scraped_count: payload.scraped_count,
        after_count: payload.after_count,
        danmaku_count: payload.danmaku_count,
      });
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
      logClientEvent("client.user.parse.error", reason instanceof Error ? reason.message : String(reason), {
        bvid: targetBvid,
      });
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsParsing(false);
    }
  }

  async function submitSpaceArchive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = ownerRef.trim();
    if (!target) {
      logClientEvent("client.user.space_archive.invalid_input", "space archive submitted without owner reference");
      setError("请输入 UP 主主页链接或 mid");
      return;
    }

    logClientEvent("client.user.space_archive.start", "user started space archive", {
      owner_ref: summarizeOwnerRef(target),
      delay: parseDelay,
    });
    setIsArchivingSpace(true);
    setIsSubmittingSpace(true);
    setError("");
    setMessage("UP 主全部视频归档已加入队列，首页会显示当前进度");
    try {
      const payload = await archiveSpaceVideos(target, {
        delay: parseDelay,
      });
      setOwnerRef(payload.mid);
      setMessage(`已加入抓取队列：${payload.mid}，排队第 ${payload.queue_position} 个`);
      logClientEvent("client.user.space_archive.accepted", "space archive task accepted", {
        mid: payload.mid,
        task_id: payload.task_id,
        queue_position: payload.queue_position,
      });
    } catch (reason: unknown) {
      logClientEvent("client.user.space_archive.error", reason instanceof Error ? reason.message : String(reason), {
        owner_ref: summarizeOwnerRef(target),
      });
      setIsArchivingSpace(false);
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsSubmittingSpace(false);
    }
  }

  function openVideo(video: VideoSummary) {
    logClientEvent("client.user.video.open_existing", "opened existing local archive", {
      bvid: video.bvid,
      title: video.title,
    });
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
              onClick={() => {
                logClientEvent("client.user.videos.refresh_click", "user refreshed video list", {
                  video_count: videos.length,
                });
                void loadVideos();
              }}
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
              onClick={() => {
                logClientEvent("client.user.settings.toggle", "user toggled parse settings", {
                  show_settings: !showSettings,
                });
                setShowSettings((value) => !value);
              }}
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
      {hasSpaceQueueWork && <ProgressBanner progress={spaceProgress} fallback="正在归档 UP 主全部视频" />}

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-5 lg:px-6">
        <StatTile icon={PlayCircle} label="视频数量" value={videos.length} tone="pink" />
        <StatTile icon={MessageCircle} label="评论档案" value={totals.comments} tone="cyan" />
        <StatTile icon={AlertTriangle} label="仍可见 / 未返回" value={`${totals.active} / ${totals.deleted}`} tone="mint" />
        <StatTile icon={Sparkles} label="弹幕档案" value={totals.danmaku} tone="amber" />
        <StatTile icon={Heart} label="评论点赞" value={totals.likes} tone="amber" />
      </section>

      <section className="mx-auto max-w-[1540px] px-4 pb-4 lg:px-6">
        <ProgressQueuePanel queue={spaceQueue} />
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
              disabled={isTaskBusy}
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
                    {duplicateVideo.bvid} · 档案 {formatNumber(duplicateVideo.comment_total_count)} · 弹幕{" "}
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
                  disabled={isTaskBusy}
                  onClick={() => {
                    logClientEvent("client.user.parse.duplicate_confirm", "user confirmed reparsing existing video", {
                      bvid: duplicateVideo.bvid,
                    });
                    void runParse(pendingParseTarget);
                  }}
                >
                  <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
                  重新抓取
                </button>
              </div>
            </div>
          )}
          <div className="mt-4 border-t border-line pt-4">
            <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
              <Users size={18} aria-hidden="true" />
              抓取UP主
            </h2>
            <form className="mt-4 grid gap-3" onSubmit={submitSpaceArchive}>
              <label className="grid gap-2 text-sm text-muted">
                UP 主主页或 mid
                <span className="flex h-11 min-w-0 items-center gap-2 rounded-md border border-line px-3 focus-within:border-bilibili focus-within:ring-2 focus-within:ring-pink-100">
                  <LinkIcon size={16} aria-hidden="true" />
                  <input
                    className="min-w-0 flex-1 bg-transparent text-ink outline-none"
                    placeholder="https://space.bilibili.com/123456"
                    value={ownerRef}
                    onChange={(event) => setOwnerRef(event.target.value)}
                  />
                </span>
              </label>
              <button
                className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-bilibili px-4 text-sm font-medium text-white transition hover:bg-[#e85f89] disabled:cursor-wait disabled:opacity-70"
                type="submit"
                disabled={isSubmittingSpace}
              >
                <RefreshCcw className={cn((isSubmittingSpace || hasSpaceQueueWork) && "animate-spin")} size={16} aria-hidden="true" />
                {isSubmittingSpace ? "加入队列中" : "抓取全部视频"}
              </button>
            </form>
          </div>
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
                <InfoRow label="数据库" value="data/comment_danmaku.db" />
              </div>
            </div>
          )}
          <div className="mt-4 border-t border-line pt-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <Users size={18} aria-hidden="true" />
                UP主分类
              </h2>
              <span className="text-xs text-muted">{ownerGroups.length} 位</span>
            </div>
            <div className="mt-3 grid gap-2">
              <OwnerFilterButton
                active={ownerFilter === "all"}
                commentCount={totals.comments}
                danmakuCount={totals.danmaku}
                name="全部视频"
                videoCount={videos.length}
                onClick={() => {
                  logClientEvent("client.user.videos.owner_filter", "user selected all owners", {
                    owner: "all",
                  });
                  setOwnerFilter("all");
                }}
              />
              <div className="max-h-[360px] overflow-y-auto pr-1">
                <div className="grid gap-2">
                  {ownerGroups.map((owner) => (
                    <OwnerFilterButton
                      active={ownerFilter === owner.key}
                      commentCount={owner.commentCount}
                      danmakuCount={owner.danmakuCount}
                      key={owner.key}
                      name={owner.name}
                      videoCount={owner.videoCount}
                      onClick={() => {
                        logClientEvent("client.user.videos.owner_filter", "user selected owner filter", {
                          owner: owner.name,
                          video_count: owner.videoCount,
                        });
                        setOwnerFilter(owner.key);
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section className="flex min-h-[560px] min-w-0 flex-col rounded-md border border-line bg-white shadow-soft">
          <div className="border-b border-line p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <ListTree size={18} aria-hidden="true" />
                {selectedOwnerName ? `${selectedOwnerName}的视频` : "视频列表"}
              </h2>
              <span className="text-sm text-muted">
                {filteredVideos.length} / {videos.length}
              </span>
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

          <div className="grid max-h-[70vh] min-h-[420px] gap-3 overflow-y-auto p-4">
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

function ProgressQueuePanel({ queue }: { queue?: ProgressQueue }) {
  const queued = queue?.queued || [];
  const recent = queue?.recent || [];
  const active = queue?.active || null;

  return (
    <section className="rounded-md border border-line bg-white shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <RefreshCcw className={cn(active && "animate-spin text-bilibili")} size={18} aria-hidden="true" />
          抓取队列
        </h2>
        <span className="text-sm text-muted">
          {active ? "1 个运行中" : "无运行任务"} · {queued.length} 个排队中
        </span>
      </div>
      <div className="grid gap-3 p-4">
        {active ? (
          <QueueTaskRow task={active} tone="active" />
        ) : (
          <div className="rounded-md border border-dashed border-line bg-[#fbfcfe] px-3 py-3 text-sm text-muted">
            暂无正在运行的抓取任务
          </div>
        )}
        {queued.length > 0 && (
          <div className="grid gap-2">
            {queued.map((task) => (
              <QueueTaskRow key={task.id} task={task} tone="queued" />
            ))}
          </div>
        )}
        {queued.length === 0 && !active && recent.length === 0 && (
          <div className="text-sm text-muted">暂无排队任务</div>
        )}
        {recent.length > 0 && (
          <div className="grid gap-2 border-t border-line pt-3">
            <div className="text-xs font-medium uppercase tracking-normal text-muted">最近完成</div>
            {recent.slice(0, 3).map((task) => (
              <QueueTaskRow key={task.id} task={task} tone="recent" />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function QueueTaskRow({ task, tone }: { task: ProgressTask; tone: "active" | "queued" | "recent" }) {
  const percent = Math.max(0, Math.min(100, Math.round(task.progress || 0)));
  const status = taskStatusLabel(task);
  const title = task.mid ? `UP ${task.mid}` : task.owner_ref || task.id;
  return (
    <div
      className={cn(
        "min-w-0 rounded-md border px-3 py-3",
        tone === "active"
          ? "border-bilibili/30 bg-pink-50"
          : tone === "queued"
            ? "border-line bg-[#fbfcfe]"
            : "border-line bg-white",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-ink">{title}</span>
            <span className="rounded bg-white px-2 py-0.5 text-xs text-muted">{status}</span>
            {task.queue_position && <span className="text-xs text-muted">排队第 {task.queue_position}</span>}
          </div>
          <div className="mt-1 truncate text-xs text-muted">
            {task.message || "等待抓取"}
            {task.current_bvid ? ` · ${task.current_bvid}` : ""}
          </div>
        </div>
        <div className="shrink-0 text-right text-xs text-muted">
          <div className="font-medium text-ink">{percent}%</div>
          <div>
            {task.complete || 0}/{task.total || 0}
          </div>
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white">
        <div className="h-full rounded-full bg-bilibili transition-all duration-300" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function taskStatusLabel(task: ProgressTask) {
  if (task.status === "running") return "运行中";
  if (task.status === "waiting") return "等待当前任务";
  if (task.status === "queued") return "排队中";
  if (task.status === "finished") return "已完成";
  if (task.status === "failed") return "失败";
  return task.status || "未知";
}

function summarizeOwnerRef(value: string) {
  return value.match(/space\.bilibili\.com\/(\d+)/)?.[1] || value.match(/^\d+$/)?.[0] || value.slice(0, 120);
}

function ownerName(video: VideoSummary) {
  return (video.owner_name || "未知UP主").trim() || "未知UP主";
}

function ownerKey(video: VideoSummary) {
  const mid = (video.owner_mid || "").trim();
  if (mid) return `mid:${mid}`;
  return `name:${ownerName(video).toLowerCase()}`;
}

type OwnerFilterButtonProps = {
  active: boolean;
  commentCount: number;
  danmakuCount: number;
  name: string;
  videoCount: number;
  onClick: () => void;
};

function OwnerFilterButton({
  active,
  commentCount,
  danmakuCount,
  name,
  videoCount,
  onClick,
}: OwnerFilterButtonProps) {
  return (
    <button
      className={cn(
        "grid w-full min-w-0 gap-1 rounded-md border px-3 py-2 text-left transition",
        active
          ? "border-bilibili bg-pink-50 text-bilibili"
          : "border-line bg-[#fbfcfe] text-ink hover:border-bilibili hover:bg-white",
      )}
      type="button"
      onClick={onClick}
    >
      <span className="flex min-w-0 items-center justify-between gap-3">
        <span className="truncate text-sm font-medium">{name}</span>
        <span className="shrink-0 rounded bg-white px-2 py-0.5 text-xs text-muted">{videoCount}</span>
      </span>
      <span className="text-xs text-muted">
        评论 {formatNumber(commentCount)} · 弹幕 {formatNumber(danmakuCount)}
      </span>
    </button>
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
          <span>档案 {formatNumber(video.comment_total_count)}</span>
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
          onClick={() =>
            logClientEvent("client.user.video_card.open_comments", "opened comments from video card", {
              bvid: video.bvid,
              title: video.title,
            })
          }
        >
          评论
          <ChevronRight size={15} aria-hidden="true" />
        </a>
        <a
          className="inline-flex h-9 items-center justify-center gap-1 rounded-md bg-ink px-3 text-sm font-medium text-white transition hover:bg-[#26344f]"
          href={`/danmaku/${video.bvid}`}
          onClick={() =>
            logClientEvent("client.user.video_card.open_danmaku", "opened danmaku from video card", {
              bvid: video.bvid,
              title: video.title,
            })
          }
        >
          弹幕
          <Sparkles size={15} aria-hidden="true" />
        </a>
      </div>
    </article>
  );
}

