import { ThumbsUp } from "lucide-react";
import type { DanmakuItem } from "../../types";
import { cn } from "../../lib/utils";
import { OwnerBadge } from "../common";
import { ColorSwatch } from "./ColorSwatch";
import { formatProgress, getDanmakuModeLabel } from "./danmakuUtils";

type DanmakuListRowProps = {
  item: DanmakuItem;
  active: boolean;
  onSelect: () => void;
};

export function DanmakuListRow({ item, active, onSelect }: DanmakuListRowProps) {
  return (
    <button
      className={cn(
        "block w-full border-b border-line/80 px-4 py-3 text-left transition hover:bg-white/70",
        active && "bg-amber-50/90 shadow-[inset_3px_0_0_#c98512]",
      )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex h-8 w-16 shrink-0 items-center justify-center rounded bg-amber-50 text-sm font-semibold text-amber ring-1 ring-amber-100">
          {formatProgress(item.progress)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="line-clamp-2 min-w-0 flex-1 break-words text-sm font-medium leading-6 text-ink">
              {item.content}
            </div>
            {item.is_up_owner && <OwnerBadge />}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{getDanmakuModeLabel(item.mode)}</span>
            <ColorSwatch color={item.color} />
            <span className="inline-flex items-center gap-1">
              <ThumbsUp size={12} aria-hidden="true" />
              {item.like_count || 0}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}
