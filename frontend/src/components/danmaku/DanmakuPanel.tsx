import { ThumbsUp } from "lucide-react";
import type { DanmakuData, DanmakuItem } from "../../types";
import { OwnerBadge } from "../common";
import { VirtualList } from "../ui/VirtualList";
import { ColorSwatch } from "./ColorSwatch";
import { formatProgress } from "./danmakuUtils";

type DanmakuPanelProps = {
  danmaku: DanmakuData | null;
  items?: DanmakuItem[];
};

export function DanmakuPanel({ danmaku, items: panelItems }: DanmakuPanelProps) {
  const items = panelItems || danmaku?.items || [];

  if (!danmaku || danmaku.metadata.total_count === 0) {
    return (
      <div className="surface-muted grid min-h-44 place-items-center rounded-md border-dashed p-6 text-center text-sm text-muted">
        暂无弹幕数据，点击刷新会重新抓取当前视频的弹幕。
      </div>
    );
  }

  return (
    <VirtualList
      className="surface-muted max-h-[640px] overflow-y-auto rounded-md p-2"
      empty={<div className="p-6 text-center text-sm text-muted">没有匹配的弹幕</div>}
      estimateSize={72}
      getKey={(item) => item.dmid}
      items={items}
      renderItem={(item) => <DanmakuRow item={item} />}
    />
  );
}

type DanmakuRowProps = {
  item: DanmakuItem;
};

function DanmakuRow({ item }: DanmakuRowProps) {
  return (
    <div className="grid grid-cols-[58px_minmax(0,1fr)] gap-3 rounded-md px-2 py-2 text-sm hover:bg-white/80">
      <span className="inline-flex h-7 items-center justify-center rounded bg-amber-50 font-medium text-amber">
        {formatProgress(item.progress)}
      </span>
      <div className="min-w-0">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 break-words leading-7 text-[#344158]">{item.content}</div>
          {item.is_up_owner && <OwnerBadge />}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>ID {item.dmid}</span>
          <ColorSwatch color={item.color} />
          <span className="inline-flex items-center gap-1">
            <ThumbsUp size={12} aria-hidden="true" />
            {item.like_count || 0}
          </span>
        </div>
      </div>
    </div>
  );
}
