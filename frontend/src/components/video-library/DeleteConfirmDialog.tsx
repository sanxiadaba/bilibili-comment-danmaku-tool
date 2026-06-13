import { AlertTriangle, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { formatNumber } from "../../lib/utils";
import type { DeleteTarget } from "./types";

type DeleteConfirmDialogProps = {
  disabled?: boolean;
  target: DeleteTarget;
  onClose: () => void;
  onConfirm: () => void;
};

export function DeleteConfirmDialog({ disabled = false, target, onClose, onConfirm }: DeleteConfirmDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const summary = useMemo(() => deleteSummary(target), [target]);
  const matched = confirmText.trim() === summary.confirmText;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/35 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="surface-card w-full max-w-lg overflow-hidden rounded-md shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-red-100 bg-red-50/80 p-4">
          <div className="min-w-0">
            <h2 className="inline-flex items-center gap-2 text-base font-semibold text-red-800">
              <AlertTriangle size={18} aria-hidden="true" />
              {summary.title}
            </h2>
            <p className="mt-1 text-sm text-red-700">{summary.subtitle}</p>
          </div>
          <button
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/80 text-muted transition hover:text-ink"
            type="button"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="grid gap-4 p-4 text-sm">
          <div className="grid gap-2 rounded-md border border-red-100 bg-white/72 p-3 text-muted">
            <div className="font-medium text-ink">{summary.name}</div>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <span>视频 {formatNumber(summary.videoCount)}</span>
              <span>评论 {formatNumber(summary.commentCount)}</span>
              <span>弹幕 {formatNumber(summary.danmakuCount)}</span>
            </div>
            <div className="text-red-700">会从当前数据库删除对应视频、评论、楼中楼、评论图片、表情和弹幕。</div>
            <div>不会删除你已经导出的独立 .db / .json 文件，也不会删除 Cookie。</div>
          </div>
          <label className="grid gap-2 text-muted">
            输入 <span className="font-mono text-ink">{summary.confirmText}</span> 确认删除
            <input
              className="input-shell h-10 rounded-md px-3 text-ink outline-none"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn-quiet inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium" type="button" onClick={onClose}>
              取消
            </button>
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-red-600 px-4 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              disabled={disabled || !matched}
              onClick={onConfirm}
            >
              <Trash2 size={16} aria-hidden="true" />
              {disabled ? "删除中" : "确认删除"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function deleteSummary(target: DeleteTarget) {
  if (target.kind === "owner") {
    return {
      title: "删除这个 UP 主的本地档案",
      subtitle: "这是不可恢复的数据库删除操作。",
      name: target.owner.name,
      videoCount: target.owner.videoCount,
      commentCount: target.owner.commentCount,
      danmakuCount: target.owner.danmakuCount,
      confirmText: target.owner.ownerMid || target.owner.name,
    };
  }
  return {
    title: "删除这个视频的本地档案",
    subtitle: "这是不可恢复的数据库删除操作。",
    name: target.video.title,
    videoCount: 1,
    commentCount: target.video.comment_total_count || 0,
    danmakuCount: target.video.danmaku_count || 0,
    confirmText: target.video.bvid,
  };
}
