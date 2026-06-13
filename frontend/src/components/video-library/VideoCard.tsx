import { ChevronRight, Download, Eye, Sparkles, Trash2 } from "lucide-react";
import { logClientEvent } from "../../api/client";
import { cn, formatFullDateTime, formatNumber, normalizeImageUrl } from "../../lib/utils";
import { dbPath } from "../../lib/videoLibrary";
import type { VideoSummary } from "../../types";

type VideoCardProps = {
  disabled: boolean;
  dbId: string;
  exporting: boolean;
  video: VideoSummary;
  onDelete: () => void;
  onExport: () => void;
};

export function VideoCard({ disabled, dbId, exporting, video, onDelete, onExport }: VideoCardProps) {
  return (
    <article className="interactive-card grid gap-3 rounded-md border border-line bg-white/70 p-3 text-left transition hover:border-bilibili hover:bg-white md:grid-cols-[180px_minmax(0,1fr)_auto]">
      <div className="relative aspect-video overflow-hidden rounded-md bg-slate-100 shadow-sm">
        {video.pic && <img className="h-full w-full object-cover" src={normalizeImageUrl(video.pic)} alt={video.title} referrerPolicy="no-referrer" />}
        <span className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs font-medium text-white shadow-sm">{video.bvid}</span>
      </div>
      <div className="min-w-0 self-center">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>{video.owner_name || "UP主"}</span>
          <span>{formatFullDateTime(video.fetched_at)}</span>
        </div>
        <h3 className="mt-2 line-clamp-2 text-base font-semibold leading-6 text-ink">{video.title}</h3>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <Eye size={13} aria-hidden="true" />
            播放 {formatNumber(video.stat_view)}
          </span>
          <span>档案 {formatNumber(video.comment_total_count)}</span>
          <span>弹幕 {formatNumber(video.danmaku_count)}</span>
          <span>可见 {formatNumber(video.active_comment_count)}</span>
          <span>未返回 {formatNumber(video.deleted_comment_count)}</span>
          <span>点赞 {formatNumber(video.comment_like_count)}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 self-center md:flex-col md:items-stretch">
        <a
          className="btn-quiet inline-flex h-9 items-center justify-center gap-1 rounded-md px-3 text-sm font-medium"
          href={dbPath(`/video/${video.bvid}`, dbId)}
          onClick={() =>
            logClientEvent("client.user.video_card.open_comments", "opened comments from video card", {
              db_id: dbId,
              bvid: video.bvid,
              title: video.title,
            })
          }
        >
          评论
          <ChevronRight size={15} aria-hidden="true" />
        </a>
        <a
          className="btn-primary inline-flex h-9 items-center justify-center gap-1 rounded-md px-3 text-sm font-medium"
          href={dbPath(`/danmaku/${video.bvid}`, dbId)}
          onClick={() =>
            logClientEvent("client.user.video_card.open_danmaku", "opened danmaku from video card", {
              db_id: dbId,
              bvid: video.bvid,
              title: video.title,
            })
          }
        >
          弹幕
          <Sparkles size={15} aria-hidden="true" />
        </a>
        <button
          className="btn-quiet inline-flex h-9 items-center justify-center gap-1 rounded-md px-3 text-sm font-medium disabled:cursor-wait disabled:opacity-60"
          type="button"
          disabled={disabled}
          onClick={onExport}
        >
          <Download className={cn(exporting && "animate-bounce")} size={15} aria-hidden="true" />
          {exporting ? "导出中" : "导出"}
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-1 rounded-md border border-red-100 bg-red-50/70 px-3 text-sm font-medium text-red-700 transition hover:border-red-300 hover:bg-red-50 disabled:cursor-wait disabled:opacity-60"
          type="button"
          disabled={disabled}
          onClick={onDelete}
        >
          <Trash2 size={15} aria-hidden="true" />
          删除
        </button>
      </div>
    </article>
  );
}
