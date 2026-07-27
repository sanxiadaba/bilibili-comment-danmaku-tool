import { Database, Download, X } from "lucide-react";
import { formatNumber } from "../../lib/utils";
import { useModalDialog } from "../../hooks/useModalDialog";
import type { ExportFormat, ExportTarget } from "../../types";

type ExportChoiceDialogProps = {
  target: ExportTarget;
  onChoose: (format: ExportFormat) => void;
  onClose: () => void;
};

export function ExportChoiceDialog({ target, onChoose, onClose }: ExportChoiceDialogProps) {
  const dialogRef = useModalDialog(true, onClose);
  const isOwner = target.kind === "owner";
  const title = isOwner ? "导出 UP 主档案" : "导出视频档案";
  const name = isOwner ? target.owner.name : target.video.title;
  const summary = isOwner
    ? `${target.owner.videoCount} 个视频 · 评论 ${formatNumber(target.owner.commentCount)} · 弹幕 ${formatNumber(target.owner.danmakuCount)}`
    : `${target.video.bvid} · 评论 ${formatNumber(target.video.comment_total_count)} · 弹幕 ${formatNumber(target.video.danmaku_count)}`;

  return (
    <div ref={dialogRef} className="fixed inset-0 z-50 grid place-items-center bg-black/30 px-4" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
      <div className="surface-card w-full max-w-lg overflow-hidden rounded-md shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-line/80 bg-white/42 p-4">
          <div className="min-w-0">
            <div className="text-base font-semibold text-ink">{title}</div>
            <div className="mt-1 line-clamp-2 text-sm text-muted">{name}</div>
            <div className="mt-1 text-xs text-muted">{summary}</div>
          </div>
          <button
            data-autofocus
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/70 text-muted transition hover:text-ink hover:shadow-sm"
            type="button"
            aria-label="关闭导出选择"
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="grid gap-3 p-4 sm:grid-cols-2">
          <button
            className="interactive-card grid min-h-28 gap-2 rounded-md border border-line bg-white/70 p-4 text-left transition hover:border-bilibili hover:bg-white"
            type="button"
            onClick={() => onChoose("sqlite")}
          >
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <Database size={17} aria-hidden="true" />
              SQLite 数据库
            </span>
            <span className="text-sm leading-6 text-muted">导出为可热插拔的独立数据库，适合继续在本工具中切换查看。</span>
          </button>
          <button
            className="interactive-card grid min-h-28 gap-2 rounded-md border border-line bg-white/70 p-4 text-left transition hover:border-bilibili hover:bg-white"
            type="button"
            onClick={() => onChoose("json")}
          >
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <Download size={17} aria-hidden="true" />
              JSON 文件
            </span>
            <span className="text-sm leading-6 text-muted">导出真实数据文件，包含视频信息、评论、楼中楼和弹幕，可再次导入。</span>
          </button>
        </div>
      </div>
    </div>
  );
}
