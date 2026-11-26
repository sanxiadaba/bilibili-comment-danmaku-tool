import { useCallback } from "react";
import { AlertTriangle, ListTree, RefreshCcw, Search } from "lucide-react";
import { VirtualList } from "../ui/VirtualList";
import { VideoCard } from "./VideoCard";
import type { VideoSummary } from "../../types";

// Cards are roughly this tall; VirtualList re-measures every mounted row, so this only decides
// the initial scroll geometry.
const VIDEO_CARD_ESTIMATE = 120;

type VideoListPanelProps = {
  activeDbId: string;
  backendTotalVideoCount: number;
  failedDatabases?: Array<{ id: string; error: string }>;
  hasMore: boolean;
  incomplete?: boolean;
  isLoading: boolean;
  query: string;
  selectedOwnerName?: string;
  totalVideoCount: number;
  videos: VideoSummary[];
  onLoadMore: () => void;
  onQueryChange: (value: string) => void;
  onRetryVideos?: () => void;
};

export function VideoListPanel({
  activeDbId,
  backendTotalVideoCount,
  failedDatabases = [],
  hasMore,
  incomplete = false,
  isLoading,
  query,
  selectedOwnerName,
  totalVideoCount,
  videos,
  onLoadMore,
  onQueryChange,
  onRetryVideos,
}: VideoListPanelProps) {
  const getKey = useCallback((video: VideoSummary) => `${video.db_id || activeDbId}:${video.bvid}`, [activeDbId]);
  const renderVideo = useCallback(
    (video: VideoSummary) => (
      <div className="pb-3">
        <VideoCard dbId={activeDbId} video={video} />
      </div>
    ),
    [activeDbId],
  );
  const emptyState =
    query.trim() || selectedOwnerName ? (
      <div className="p-6 text-center text-sm text-muted">没有匹配的视频。清空搜索，或在左侧切换到别的 UP 主试试。</div>
    ) : (
      <div className="grid gap-2 p-8 text-center text-sm text-muted">
        <div className="text-base font-semibold text-ink">还没有归档任何视频</div>
        <div>在左侧粘贴视频链接（或 BV 号）点「解析视频」；想整理某个 UP 主，就粘贴主页地址点「抓取全部视频」。</div>
        <div>归档完成后，视频会出现在这里，点「评论」或「弹幕」就能查看。</div>
      </div>
    );

  return (
    <section className="surface-card flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-md">
      {(incomplete || failedDatabases.length > 0) && (
        <div
          className="flex shrink-0 flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50/85 px-4 py-2 text-xs text-amber-900"
          title={failedDatabases.map((database) => `${database.id}：${database.error}`).join("\n")}
        >
          <AlertTriangle className="shrink-0 text-amber-600" size={14} aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {failedDatabases.length
              ? `有 ${failedDatabases.length} 个数据库读取失败，视频列表可能不完整：${failedDatabases
                  .map((database) => database.id)
                  .join("、")}`
              : "部分数据库读取失败，视频列表可能不完整"}
          </span>
          {onRetryVideos && (
            <button className="btn-quiet inline-flex h-7 shrink-0 items-center gap-1 rounded px-2 text-xs font-medium" type="button" onClick={onRetryVideos}>
              <RefreshCcw size={12} aria-hidden="true" />
              重试
            </button>
          )}
        </div>
      )}

      <div className="shrink-0 border-b border-line/80 bg-white/45 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <ListTree size={18} aria-hidden="true" />
            {selectedOwnerName ? `${selectedOwnerName}的视频` : "视频列表"}
          </h2>
          <span className="text-sm text-muted">
            {videos.length} / {backendTotalVideoCount || totalVideoCount}
          </span>
          <label className="input-shell flex h-10 min-w-0 items-center gap-2 rounded-md px-3 text-sm text-muted">
            <Search size={16} aria-hidden="true" />
            <input
              aria-label="搜索标题、UP 主或 BV 号"
              className="min-w-0 bg-transparent text-ink outline-none"
              placeholder="搜索标题、UP 或 BV"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </label>
        </div>
      </div>

      {isLoading ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4 pr-3">
          <div className="p-6 text-center text-sm text-muted">正在载入视频库</div>
        </div>
      ) : (
        <VirtualList
          className="min-h-0 flex-1 overflow-y-auto p-4 pr-3"
          empty={emptyState}
          estimateSize={VIDEO_CARD_ESTIMATE}
          getKey={getKey}
          items={videos}
          renderItem={renderVideo}
        />
      )}

      {!isLoading && hasMore && (
        <div className="shrink-0 border-t border-line/80 p-3">
          <button
            className="btn-quiet mx-auto flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium"
            type="button"
            onClick={onLoadMore}
          >
            加载更多视频（剩余 {(backendTotalVideoCount || totalVideoCount) - videos.length}）
          </button>
        </div>
      )}
    </section>
  );
}
