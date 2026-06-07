import { ThumbsUp } from "lucide-react";
import type { DanmakuData, DanmakuItem } from "../../types";
import { formatFullDateTime, formatNumber } from "../../lib/utils";
import { OwnerBadge } from "../common";
import { ColorSwatch } from "./ColorSwatch";
import { formatProgress } from "./danmakuUtils";

type DanmakuPanelProps = {
  danmaku: DanmakuData | null;
  items?: DanmakuItem[];
  compact?: boolean;
};

export function DanmakuPanel({ danmaku, items: panelItems, compact = false }: DanmakuPanelProps) {
  const items = panelItems || danmaku?.items || [];
  const buckets = danmaku?.buckets || [];
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const fetchedAt = danmaku?.metadata.fetched_at ? formatFullDateTime(danmaku.metadata.fetched_at) : "";

  if (!danmaku || danmaku.metadata.total_count === 0) {
    return (
      <div className="grid min-h-44 place-items-center rounded-md border border-dashed border-line bg-[#fbfcfe] p-6 text-center text-sm text-muted">
        暂无弹幕数据，点击刷新会重新抓取当前视频的评论和弹幕。
      </div>
    );
  }

  if (compact) {
    return (
      <div className="max-h-[640px] overflow-y-auto rounded-md border border-line bg-[#fbfcfe] p-2">
        {items.map((item) => (
          <DanmakuRow item={item} key={item.dmid} />
        ))}
        {items.length === 0 && <div className="p-6 text-center text-sm text-muted">没有匹配的弹幕</div>}
      </div>
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <div className="mb-3 grid gap-2 text-sm sm:grid-cols-3">
          <DanmakuMetric label="CID" value={danmaku.metadata.cid || "-"} />
          <DanmakuMetric label="覆盖时间" value={formatProgress(danmaku.metadata.max_progress)} />
          <DanmakuMetric label="抓取时间" value={fetchedAt || "-"} />
        </div>
        <div className="h-56 w-full max-w-full overflow-hidden rounded-md border border-line bg-[#fbfcfe] p-3">
          <div className="flex h-44 min-w-0 items-end gap-1 border-b border-line">
            {buckets.map((bucket) => (
              <div
                className="group flex min-w-0 flex-1 flex-col items-center justify-end"
                key={bucket.bucket_start}
                title={`${bucket.label}：${bucket.count} 条`}
              >
                <div
                  className="w-full rounded-t bg-amber"
                  style={{ height: `${Math.max(4, (bucket.count / max) * 100)}%` }}
                />
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted">
            <span className="min-w-0 truncate">{buckets[0]?.label || "00:00"}</span>
            <span className="shrink-0">按视频进度聚合</span>
            <span className="min-w-0 truncate text-right">{buckets.at(-1)?.label || "-"}</span>
          </div>
        </div>
      </div>

      <div className="min-w-0 rounded-md border border-line bg-[#fbfcfe]">
        <div className="flex h-11 items-center justify-between border-b border-line px-3 text-sm">
          <span className="font-semibold text-ink">弹幕明细</span>
          <span className="text-muted">{formatNumber(items.length)} 条</span>
        </div>
        <div className="max-h-[640px] overflow-y-auto p-2">
          {items.map((item) => (
            <DanmakuRow item={item} key={item.dmid} />
          ))}
        </div>
      </div>
    </div>
  );
}

type DanmakuMetricProps = {
  label: string;
  value: string;
};

function DanmakuMetric({ label, value }: DanmakuMetricProps) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-[#fbfcfe] px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-ink">{value}</div>
    </div>
  );
}

type DanmakuRowProps = {
  item: DanmakuItem;
};

function DanmakuRow({ item }: DanmakuRowProps) {
  return (
    <div className="grid grid-cols-[58px_minmax(0,1fr)] gap-3 rounded-md px-2 py-2 text-sm hover:bg-white">
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
