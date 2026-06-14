import { ListTree, Search } from "lucide-react";
import { VideoCard } from "./VideoCard";
import type { VideoSummary } from "../../types";

type VideoListPanelProps = {
  activeDbId: string;
  backendTotalVideoCount: number;
  hasMore: boolean;
  isLoading: boolean;
  query: string;
  selectedOwnerName?: string;
  totalVideoCount: number;
  videos: VideoSummary[];
  onLoadMore: () => void;
  onQueryChange: (value: string) => void;
};

export function VideoListPanel({
  activeDbId,
  backendTotalVideoCount,
  hasMore,
  isLoading,
  query,
  selectedOwnerName,
  totalVideoCount,
  videos,
  onLoadMore,
  onQueryChange,
}: VideoListPanelProps) {
  return (
    <section className="surface-card flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-md">
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
              className="min-w-0 bg-transparent text-ink outline-none"
              placeholder="搜索标题、UP 或 BV"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </label>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-4 pr-3">
        {isLoading && <div className="p-6 text-center text-sm text-muted">正在载入视频库</div>}
        {!isLoading &&
          videos.map((video) => (
            <VideoCard
              dbId={activeDbId}
              key={video.bvid}
              video={video}
            />
          ))}
        {!isLoading && hasMore && !query && !selectedOwnerName && (
          <button
            className="btn-quiet mx-auto inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium"
            type="button"
            onClick={onLoadMore}
          >
            加载更多视频（剩余 {(backendTotalVideoCount || totalVideoCount) - videos.length}）
          </button>
        )}
        {!isLoading && videos.length === 0 && (
          <div className="p-6 text-center text-sm text-muted">暂无匹配的视频</div>
        )}
      </div>
    </section>
  );
}
