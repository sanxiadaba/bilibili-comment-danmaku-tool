import { AlertTriangle, CheckCircle2, FolderOpen, X, XCircle } from "lucide-react";
import { cn } from "../../lib/utils";
import type { NoticeState } from "./types";

export function NoticeDialog({ notice, onClose }: { notice: NoticeState; onClose: () => void }) {
  const Icon = notice.kind === "success" ? CheckCircle2 : notice.kind === "warning" ? AlertTriangle : XCircle;
  const tone =
    notice.kind === "success"
      ? "text-emerald-700 bg-emerald-50 border-emerald-100"
      : notice.kind === "warning"
        ? "text-amber-700 bg-amber-50 border-amber-100"
        : "text-red-700 bg-red-50 border-red-100";

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 px-4" role="dialog" aria-modal="true">
      <div className="surface-card w-full max-w-md rounded-md shadow-xl">
        <div className={cn("flex items-start gap-3 border-b p-4", tone)}>
          <Icon className="mt-0.5 shrink-0" size={20} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="text-base font-semibold text-ink">{notice.title}</div>
            <div className="mt-1 break-words text-sm leading-6">{notice.message}</div>
          </div>
          <button
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/80 text-muted transition hover:text-ink hover:shadow-sm"
            type="button"
            aria-label="关闭提示"
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="flex flex-wrap justify-end gap-2 p-4">
          {notice.onAction && (
            <button
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium"
              type="button"
              onClick={() => {
                void notice.onAction?.();
              }}
            >
              <FolderOpen size={16} aria-hidden="true" />
              {notice.actionLabel || "打开所在文件夹"}
            </button>
          )}
          <button
            className="btn-primary inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium"
            type="button"
            onClick={onClose}
          >
            知道了
          </button>
        </div>
      </div>
    </div>
  );
}
