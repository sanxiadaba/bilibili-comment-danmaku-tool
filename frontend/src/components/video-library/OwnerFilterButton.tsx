import { Download } from "lucide-react";
import { cn, formatNumber } from "../../lib/utils";

type OwnerFilterButtonProps = {
  active: boolean;
  commentCount: number;
  danmakuCount: number;
  exportDisabled?: boolean;
  exporting?: boolean;
  name: string;
  videoCount: number;
  onExport?: () => void;
  onClick: () => void;
};

export function OwnerFilterButton({
  active,
  commentCount,
  danmakuCount,
  exportDisabled = false,
  exporting = false,
  name,
  videoCount,
  onExport,
  onClick,
}: OwnerFilterButtonProps) {
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
      </button>
      {onExport && (
        <button
          className="inline-flex w-20 items-center justify-center gap-1 border-l border-line bg-white/80 text-xs font-medium text-muted transition hover:bg-white hover:text-bilibili disabled:cursor-wait disabled:opacity-60"
          type="button"
          aria-label={`导出 ${name} 的UP主数据库`}
          title={`导出 ${name} 的UP主数据库`}
          disabled={exportDisabled}
          onClick={onExport}
        >
          <Download className={cn(exporting && "animate-bounce")} size={16} aria-hidden="true" />
          导出
        </button>
      )}
    </div>
  );
}
