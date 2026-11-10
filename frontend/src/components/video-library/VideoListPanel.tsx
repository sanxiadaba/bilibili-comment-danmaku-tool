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
              aria-label="搜索标题、UP 主或 BV 号"
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
              key={`${video.db_id || activeDbId}:${video.bvid}`}
              video={video}
            />
          ))}
        {!isLoading && hasMore && (
          <button
            className="btn-quiet mx-auto inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium"
            type="button"
            onClick={onLoadMore}
          >
            加载更多视频（剩余 {(backendTotalVideoCount || totalVideoCount) - videos.length}）
          </button>
        )}
        {!isLoading && videos.length === 0 && (
          query.trim() || selectedOwnerName ? (
            <div className="p-6 text-center text-sm text-muted">没有匹配的视频。清空搜索，或在左侧切换到别的 UP 主试试。</div>
          ) : (
            <div className="grid gap-2 p-8 text-center text-sm text-muted">
              <div className="text-base font-semibold text-ink">还没有归档任何视频</div>
              <div>在左侧粘贴视频链接（或 BV 号）点「解析视频」；想整理某个 UP 主，就粘贴主页地址点「抓取全部视频」。</div>
              <div>归档完成后，视频会出现在这里，点「评论」或「弹幕」就能查看。</div>
            </div>
          )
        )}
      </div>
    </section>
  );
}
