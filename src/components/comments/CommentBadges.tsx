import { AlertTriangle } from "lucide-react";
import { cn } from "../../lib/utils";
import { OwnerBadge } from "../common";

type DeletedBadgeProps = {
  className?: string;
};

export function DeletedBadge({ className }: DeletedBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700",
        className,
      )}
      title="这条评论在最近一次刷新中没有被 Bilibili API 返回，已保留在本地档案中"
    >
      <AlertTriangle size={12} aria-hidden="true" />
      本次未返回
    </span>
  );
}

export { OwnerBadge };
