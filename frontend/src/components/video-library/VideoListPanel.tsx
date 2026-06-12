import { ListTree, Search } from "lucide-react";
import { VideoCard } from "./VideoCard";
import type { VideoSummary } from "../../types";

type VideoListPanelProps = {
  activeDbId: string;
  exportingKey: string;
  isLoading: boolean;
  query: string;
  selectedOwnerName?: string;
  totalVideoCount: number;
  videos: VideoSummary[];
  onExport: (video: VideoSummary) => void;
  onQueryChange: (value: string) => void;
};

export function VideoListPanel({
  activeDbId,
  exportingKey,
  isLoading,
  query,
  selectedOwnerName,
  totalVideoCount,
  videos,
  onExport,
  onQueryChange,
}: VideoListPanelProps) {
  return (
    <section className="flex min-h-[560px] min-w-0 flex-col rounded-md border border-line bg-white shadow-soft">
      <div className="border-b border-line p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <ListTree size={18} aria-hidden="true" />
            {selectedOwnerName ? `${selectedOwnerName}的视频` : "视频列表"}
          </h2>
          <span className="text-sm text-muted">
            {videos.length} / {totalVideoCount}
          </span>
          <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
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

      <div className="grid max-h-[70vh] min-h-[420px] content-start gap-3 overflow-y-auto p-4">
        {isLoading && <div className="p-6 text-center text-sm text-muted">正在载入视频库</div>}
        {!isLoading &&
          videos.map((video) => (
            <VideoCard
              disabled={Boolean(exportingKey)}
              dbId={activeDbId}
              exporting={exportingKey === `video:${video.bvid}`}
              key={video.bvid}
              video={video}
              onExport={() => onExport(video)}
            />
          ))}
        {!isLoading && videos.length === 0 && (
          <div className="p-6 text-center text-sm text-muted">暂无匹配的视频</div>
        )}
      </div>
    </section>
  );
}
