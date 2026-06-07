import {
  AlertTriangle,
  BarChart3,
  Clock3,
  Database,
  Download,
  ExternalLink,
  Eye,
  Filter,
  Heart,
  ListTree,
  MapPin,
  MessageCircle,
  RefreshCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  ThumbsUp,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchCommentData, refreshCommentData } from "../api/client";
import { AuthorList, LocationChart, TimeChart } from "../components/comments/CommentCharts";
import { DeletedBadge } from "../components/comments/CommentBadges";
import { CommentDetail } from "../components/comments/CommentDetail";
import { CommentRow } from "../components/comments/CommentRow";
import { CommentImages, CommentText } from "../components/comments/CommentText";
import { sortLabels } from "../components/comments/commentUtils";
import { Metric, Panel, ProgressBanner } from "../components/common";
import { Avatar } from "../components/ui/Avatar";
import { Segmented } from "../components/ui/Segmented";
import { StatTile } from "../components/ui/StatTile";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { csvCell } from "../lib/csv";
import {
  cn,
  filterComments,
  flattenThread,
  formatFullDateTime,
  formatNumber,
  getCommentAuthor,
  getCommentAvatar,
  getMaxLike,
  hourlyBuckets,
  locationBuckets,
  normalizeImageUrl,
  sortComments,
  topAuthors,
  topLiked,
} from "../lib/utils";
import type { CommentData, CommentNode, LevelFilter, SortMode } from "../types";

export function VideoDetailPage({ bvid }: { bvid?: string }) {
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
                Bilibili 评论弹幕工具
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
