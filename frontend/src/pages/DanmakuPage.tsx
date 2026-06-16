import {
  AlertTriangle,
  BarChart3,
  Clock3,
  Database,
  Download,
  Eye,
  ExternalLink,
  Filter,
  ListTree,
  MessageCircle,
  RefreshCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  ThumbsUp,
} from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { fetchDanmakuData, logClientEvent, refreshDanmakuData } from "../api/client";
import { DanmakuColorList, DanmakuModeChart, DanmakuTimelineChart, RepeatedDanmakuList } from "../components/danmaku/DanmakuCharts";
import { DanmakuDetail } from "../components/danmaku/DanmakuDetail";
import { DanmakuListRow } from "../components/danmaku/DanmakuList";
import { DanmakuPanel } from "../components/danmaku/DanmakuPanel";
import {
  buildDanmakuBuckets,
  buildDanmakuColorStats,
  buildDanmakuModeStats,
  buildRepeatedDanmakuContent,
  colorNumberToHex,
  danmakuModeLabels,
  danmakuSortLabels,
  formatProgress,
  getDanmakuModeGroup,
  sortDanmakuItems,
  type DanmakuModeFilter,
  type DanmakuSortMode,
} from "../components/danmaku/danmakuUtils";
import { Panel, ProgressBanner } from "../components/common";
import { Segmented } from "../components/ui/Segmented";
import { StatTile } from "../components/ui/StatTile";
import { VirtualList } from "../components/ui/VirtualList";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { csvCell } from "../lib/csv";
import { cn, formatFullDateTime, formatNumber } from "../lib/utils";
import { dbPath } from "../lib/videoLibrary";
import type { DanmakuData } from "../types";

const DANMAKU_PAGE_SIZE = 2000;

export function DanmakuPage({ bvid }: { bvid?: string }) {
  const dbId = useMemo(() => new URLSearchParams(window.location.search).get("db_id") || "main", []);
  const [danmaku, setDanmaku] = useState<DanmakuData | null>(null);
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<DanmakuSortMode>("like_desc");
  const [modeFilter, setModeFilter] = useState<DanmakuModeFilter>("all");
  const [progressRange, setProgressRange] = useState(100);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const deferredQuery = useDeferredValue(query);
  const danmakuProgress = useProgressPolling(isRefreshing, "danmaku");

  const applyDanmakuPayload = useCallback((payload: DanmakuData, mode: "replace" | "append" = "replace") => {
    setDanmaku((current) => {
      if (mode === "append" && current?.metadata.bvid === payload.metadata.bvid) {
        const seen = new Set(current.items.map((item) => item.dmid));
        return {
          ...payload,
          items: [...current.items, ...payload.items.filter((item) => !seen.has(item.dmid))],
        };
      }
      return payload;
    });
    setSelectedId((current) => {
      if (mode === "append" && current) return current;
      const currentExists = payload.items.some((item) => item.dmid === current);
      return currentExists ? current : payload.items[0]?.dmid || "";
    });
  }, []);

  const loadDanmaku = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const payload = await fetchDanmakuData(bvid, dbId, { limit: DANMAKU_PAGE_SIZE });
      applyDanmakuPayload(payload);
      setMessage("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsLoading(false);
    }
  }, [applyDanmakuPayload, bvid, dbId]);

  useEffect(() => {
    void loadDanmaku();
  }, [loadDanmaku]);

  const loadMoreDanmaku = useCallback(async () => {
    if (!danmaku?.metadata.has_more || isLoadingMore) return;
    setIsLoadingMore(true);
    setError("");
    try {
      const payload = await fetchDanmakuData(danmaku.metadata.bvid, dbId, {
        limit: DANMAKU_PAGE_SIZE,
        offset: danmaku.items.length,
      });
      applyDanmakuPayload(payload, "append");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsLoadingMore(false);
    }
  }, [applyDanmakuPayload, danmaku, dbId, isLoadingMore]);

  const allItems = danmaku?.items || [];
  const maxProgress = Math.max(0, danmaku?.metadata.max_progress || 0);
  const progressLimit = maxProgress ? (maxProgress * progressRange) / 100 : 0;

  const filteredItems = useMemo(() => {
    const items = danmaku?.items || [];
    const needle = deferredQuery.trim().toLowerCase();
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
  }, [danmaku?.items, deferredQuery, modeFilter, progressLimit]);

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
    logClientEvent("client.user.danmaku.refresh_start", "user started danmaku refresh", {
      db_id: dbId,
      bvid: danmaku?.metadata.bvid || bvid,
    });
    setIsRefreshing(true);
    setError("");
    setMessage("正在重新抓取弹幕");
    try {
      const payload = await refreshDanmakuData(danmaku?.metadata.bvid || bvid, dbId);
      applyDanmakuPayload(payload);
      logClientEvent("client.user.danmaku.refresh_success", "danmaku refresh completed", {
        db_id: dbId,
        bvid: payload.metadata.bvid,
        after_count: payload.metadata.total_count,
        scraped_count: payload.refresh?.scraped_count,
        warning: Boolean(payload.refresh?.warning),
      });
      setMessage(
        payload.refresh?.warning ||
          `已刷新弹幕：本次抓到 ${payload.refresh?.scraped_count ?? payload.metadata.total_count} 条，档案共 ${
            payload.metadata.total_count
          } 条`,
      );
    } catch (reason: unknown) {
      logClientEvent("client.user.danmaku.refresh_error", reason instanceof Error ? reason.message : String(reason), {
        db_id: dbId,
        bvid: danmaku?.metadata.bvid || bvid,
      });
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsRefreshing(false);
    }
  }

  function exportDanmaku() {
    if (!danmaku) return;
    logClientEvent("client.user.danmaku.export", "user exported filtered danmaku", {
      bvid: danmaku.metadata.bvid,
      filtered_count: sortedItems.length,
      total_count: totalCount,
      sort: sortMode,
      mode_filter: modeFilter,
    });
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
    logClientEvent("client.user.danmaku.reset_filters", "user reset danmaku filters", {
      bvid: danmaku?.metadata.bvid || bvid,
      previous_sort: sortMode,
      previous_mode: modeFilter,
      previous_progress_range: progressRange,
    });
    setQuery("");
    setSortMode("like_desc");
    setModeFilter("all");
    setProgressRange(100);
  }

  if (isLoading && !danmaku) {
    return (
      <main className="app-shell grid place-items-center">
        <div className="surface-card flex items-center gap-3 rounded-md px-5 py-4 text-sm text-muted">
          <RefreshCcw className="animate-spin" size={18} aria-hidden="true" />
          正在载入弹幕数据
        </div>
      </main>
    );
  }

  const totalCount = danmaku?.metadata.total_count ?? 0;
  const fetchedAt = danmaku?.metadata.fetched_at ? formatFullDateTime(danmaku.metadata.fetched_at) : "-";

  return (
    <main className="app-shell">
      <section className="app-header">
        <div className="mx-auto grid max-w-[1800px] gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-6 2xl:px-8">
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
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium"
              href={dbPath("/", dbId)}
              onClick={() =>
                logClientEvent("client.user.danmaku.nav_library", "user opened video library from danmaku", {
                  db_id: dbId,
                  bvid: danmaku?.metadata.bvid || bvid,
                })
              }
            >
              <Database size={16} aria-hidden="true" />
              视频库
            </a>
            <a
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium"
              href={dbPath(`/video/${danmaku?.metadata.bvid || bvid || ""}`, dbId)}
              onClick={() =>
                logClientEvent("client.user.danmaku.nav_comments", "user opened comments from danmaku", {
                  db_id: dbId,
                  bvid: danmaku?.metadata.bvid || bvid,
                })
              }
            >
              <MessageCircle size={16} aria-hidden="true" />
              评论页
            </a>
            <button
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
              type="button"
              onClick={refreshCurrentDanmaku}
              disabled={isRefreshing}
            >
              <RefreshCcw className={cn(isRefreshing && "animate-spin")} size={16} aria-hidden="true" />
              {isRefreshing ? "抓取中" : "刷新弹幕"}
            </button>
            <a
              className="btn-primary inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium"
              href={`https://www.bilibili.com/video/${danmaku?.metadata.bvid || bvid || ""}`}
              rel="noreferrer"
              target="_blank"
              onClick={() =>
                logClientEvent("client.user.danmaku.open_source_video", "user opened source video from danmaku", {
                  bvid: danmaku?.metadata.bvid || bvid,
                })
              }
            >
              <ExternalLink size={16} aria-hidden="true" />
              打开视频
            </a>
          </div>
        </div>
      </section>

      {error && (
        <section className="border-b border-red-100 bg-red-50">
          <div className="mx-auto max-w-[1800px] px-4 py-2 text-sm text-red-700 lg:px-6 2xl:px-8">{error}</div>
        </section>
      )}

      {message && !error && (
        <section className="border-b border-cyan-100 bg-cyan-50">
          <div className="mx-auto max-w-[1800px] px-4 py-2 text-sm text-cyan-700 lg:px-6 2xl:px-8">{message}</div>
        </section>
      )}

      {isRefreshing && <ProgressBanner progress={danmakuProgress} fallback="正在重新抓取弹幕" />}

      <section className="mx-auto grid max-w-[1800px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-5 lg:px-6 2xl:px-8">
        <StatTile icon={Sparkles} label="弹幕总数" value={totalCount} tone="amber" />
        <StatTile icon={Filter} label="当前匹配" value={sortedItems.length} tone="cyan" />
        <StatTile icon={Clock3} label="视频覆盖" value={formatProgress(danmaku?.metadata.max_progress)} tone="mint" />
        <StatTile icon={BarChart3} label="峰值片段" value={peakBucket?.label || "-"} tone="pink" />
        <StatTile icon={Database} label="CID" value={danmaku?.metadata.cid || "-"} tone="amber" />
      </section>

      <section className="mx-auto grid max-w-[1800px] gap-4 px-4 pb-6 lg:grid-cols-[380px_minmax(0,1fr)] lg:px-6 2xl:grid-cols-[400px_minmax(0,1fr)_440px] 2xl:px-8">
        <aside className="surface-card flex max-h-[calc(100vh-2rem)] min-w-0 flex-col self-start overflow-hidden rounded-md lg:sticky lg:top-4">
          <div className="border-b border-line/80 bg-white/42 p-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={17} />
              <input
                className="input-shell h-10 w-full rounded-md pl-10 pr-3 text-sm outline-none"
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
                className="btn-quiet inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted"
                type="button"
                onClick={resetDanmakuFilters}
              >
                <RefreshCcw size={15} aria-hidden="true" />
                重置
              </button>
              <button
                className="btn-quiet inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted disabled:opacity-60"
                type="button"
                onClick={exportDanmaku}
                disabled={!danmaku}
              >
                <Download size={15} aria-hidden="true" />
                导出
              </button>
            </div>

            <label className="input-shell mt-3 flex h-10 min-w-0 items-center gap-2 rounded-md px-3 text-sm text-muted">
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

          <VirtualList
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
            empty={<div className="p-6 text-center text-sm text-muted">没有匹配的弹幕</div>}
            estimateSize={92}
            getKey={(item) => item.dmid}
            items={sortedItems}
            renderItem={(item) => (
              <DanmakuListRow
                active={selectedItem?.dmid === item.dmid}
                item={item}
                onSelect={() => {
                  logClientEvent("client.user.danmaku.select_item", "user selected danmaku item", {
                    bvid: danmaku?.metadata.bvid || bvid,
                    dmid: item.dmid,
                    like_count: item.like_count || 0,
                    progress: item.progress,
                  });
                  setSelectedId(item.dmid);
                }}
              />
            )}
          />
          {danmaku?.metadata.has_more && (
            <div className="border-t border-line p-3">
              <button
                className="btn-secondary flex h-10 w-full items-center justify-center gap-2 rounded-md px-3 text-sm font-medium"
                type="button"
                disabled={isLoadingMore}
                onClick={() => void loadMoreDanmaku()}
              >
                <RefreshCcw className={cn(isLoadingMore && "animate-spin")} size={16} aria-hidden="true" />
                {isLoadingMore
                  ? "加载中"
                  : `加载更多 ${formatNumber(allItems.length)} / ${formatNumber(danmaku.metadata.total_count)}`}
              </button>
            </div>
          )}
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
            <RepeatedDanmakuList
              items={repeatedContent}
              onSelect={(item) => {
                logClientEvent("client.user.danmaku.select_repeated", "user selected repeated danmaku", {
                  bvid: danmaku?.metadata.bvid || bvid,
                  dmid: item.sample.dmid,
                  repeat_count: item.count,
                });
                setSelectedId(item.sample.dmid);
              }}
            />
          </Panel>

          <Panel icon={Sparkles} title="弹幕明细" action="全量可滚动">
            <DanmakuPanel danmaku={danmaku} items={sortedItems} compact />
          </Panel>
        </section>

        <aside className="surface-card min-w-0 overflow-hidden rounded-md lg:col-span-2 lg:min-h-[720px] 2xl:col-span-1">
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
