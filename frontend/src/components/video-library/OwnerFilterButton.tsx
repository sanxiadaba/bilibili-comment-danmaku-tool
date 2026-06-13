import { Database, Download, Trash2 } from "lucide-react";
import { cn, formatNumber } from "../../lib/utils";
import { formatBytes } from "../../lib/videoLibrary";

type OwnerFilterButtonProps = {
  active: boolean;
  commentCount: number;
  danmakuCount: number;
  exportDisabled?: boolean;
  exporting?: boolean;
  name: string;
  storageBytes?: number;
  videoCount: number;
  onDelete?: () => void;
  onExportJson?: () => void;
  onExportSqlite?: () => void;
  onClick: () => void;
};

export function OwnerFilterButton({
  active,
  commentCount,
  danmakuCount,
  exportDisabled = false,
  exporting = false,
  name,
  storageBytes,
  videoCount,
  onDelete,
  onExportJson,
  onExportSqlite,
  onClick,
}: OwnerFilterButtonProps) {
  const hasActions = onExportSqlite || onExportJson || onDelete;

  return (
    <div
      className={cn(
        "interactive-card grid min-w-0 grid-cols-[minmax(0,1fr)_auto] overflow-hidden rounded-md border transition",
        active ? "border-bilibili bg-pink-50/90 text-bilibili shadow-sm" : "border-line bg-white/66 text-ink hover:border-bilibili hover:bg-white",
      )}
    >
      <button className="grid min-w-0 gap-1 px-3 py-2 text-left" type="button" onClick={onClick}>
        <span className="flex min-w-0 items-center justify-between gap-3">
          <span className="truncate text-sm font-medium">{name}</span>
          <span className="shrink-0 rounded bg-white px-2 py-0.5 text-xs text-muted">{videoCount}</span>
        </span>
        <span className="text-xs text-muted">
          评论 {formatNumber(commentCount)} · 弹幕 {formatNumber(danmakuCount)}
        </span>
        {typeof storageBytes === "number" && storageBytes > 0 && (
          <span className="text-xs text-muted">估算占用 {formatBytes(storageBytes)}</span>
        )}
      </button>
      {hasActions && (
        <div className="grid w-20 border-l border-line bg-white/80">
          {onExportSqlite && (
            <button
              className="inline-flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium text-muted transition hover:bg-white hover:text-bilibili disabled:cursor-wait disabled:opacity-60"
              type="button"
              aria-label={`导出 ${name} 的 SQLite 数据库`}
              title={`导出 ${name} 的 SQLite 数据库`}
              disabled={exportDisabled}
              onClick={onExportSqlite}
            >
              <Database className={cn(exporting && "animate-bounce")} size={15} aria-hidden="true" />
              DB
            </button>
          )}
          {onExportJson && (
            <button
              className="inline-flex items-center justify-center gap-1 border-t border-line px-2 py-1.5 text-xs font-medium text-muted transition hover:bg-white hover:text-bilibili disabled:cursor-wait disabled:opacity-60"
              type="button"
              aria-label={`导出 ${name} 的 JSON 文件`}
              title={`导出 ${name} 的 JSON 文件`}
              disabled={exportDisabled}
              onClick={onExportJson}
            >
              <Download className={cn(exporting && "animate-bounce")} size={15} aria-hidden="true" />
              JSON
            </button>
          )}
          {onDelete && (
            <button
              className="inline-flex items-center justify-center gap-1 border-t border-line px-2 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:cursor-wait disabled:opacity-60"
              type="button"
              aria-label={`删除 ${name} 的本地档案`}
              title={`删除 ${name} 的本地档案`}
              disabled={exportDisabled}
              onClick={onDelete}
            >
              <Trash2 size={15} aria-hidden="true" />
              删除
            </button>
          )}
        </div>
      )}
    </div>
  );
}
