import type { DanmakuItem } from "../../types";
import { formatNumber } from "../../lib/utils";
import { ColorSwatch } from "./ColorSwatch";
import {
  colorNumberToHex,
  formatProgress,
  type DanmakuBucket,
  type DanmakuModeFilter,
} from "./danmakuUtils";

type DanmakuTimelineChartProps = {
  allBuckets: DanmakuBucket[];
  filteredBuckets: DanmakuBucket[];
};

export function DanmakuTimelineChart({ allBuckets, filteredBuckets }: DanmakuTimelineChartProps) {
  const filteredByTime = new Map(filteredBuckets.map((bucket) => [bucket.bucket_start, bucket.count]));
  const max = Math.max(1, ...allBuckets.map((bucket) => bucket.count));

  if (!allBuckets.length) {
    return (
      <div className="surface-muted grid min-h-44 place-items-center rounded-md border-dashed p-6 text-center text-sm text-muted">
        暂无可绘制的弹幕分布
      </div>
    );
  }

  return (
    <div className="h-72 w-full max-w-full overflow-hidden">
      <div className="flex h-60 min-w-0 items-end gap-1 border-b border-line">
        {allBuckets.map((bucket) => {
          const filteredCount = filteredByTime.get(bucket.bucket_start) || 0;
          return (
            <div className="group flex min-w-0 flex-1 flex-col items-center justify-end gap-1" key={bucket.bucket_start}>
              <div className="relative flex h-52 w-full items-end rounded-t bg-slate-100">
                <div
                  className="w-full rounded-t bg-amber/30"
                  style={{ height: `${Math.max(4, (bucket.count / max) * 100)}%` }}
                />
                <div
                  className="absolute bottom-0 w-full rounded-t bg-amber"
                  style={{ height: filteredCount ? `${Math.max(4, (filteredCount / max) * 100)}%` : 0 }}
                />
              </div>
              <span className="hidden text-[10px] text-muted group-hover:block">{bucket.count}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex min-w-0 items-center justify-between gap-3 text-xs text-muted">
        <span className="min-w-0 truncate">{allBuckets[0]?.label || "00:00"}</span>
        <span className="inline-flex shrink-0 items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded-sm bg-amber/30" />
            全部
          </span>
          <span className="inline-flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded-sm bg-amber" />
            筛选
          </span>
        </span>
        <span className="min-w-0 truncate text-right">{allBuckets.at(-1)?.label || "-"}</span>
      </div>
    </div>
  );
}

type DanmakuModeChartProps = {
  stats: Array<{ mode: DanmakuModeFilter; label: string; count: number }>;
  total: number;
};

export function DanmakuModeChart({ stats, total }: DanmakuModeChartProps) {
  const max = Math.max(1, ...stats.map((item) => item.count));
  return (
    <div className="space-y-3">
      {stats.map((item) => (
        <div className="grid grid-cols-[56px_minmax(0,1fr)_48px] items-center gap-3 text-sm" key={item.mode}>
          <span className="truncate font-medium text-ink">{item.label}</span>
          <div className="h-3 overflow-hidden rounded-sm bg-slate-100">
            <div className="h-full rounded-sm bg-cyan" style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <span className="text-right text-muted">{total ? Math.round((item.count / total) * 100) : 0}%</span>
        </div>
      ))}
    </div>
  );
}

type DanmakuColorListProps = {
  colors: Array<{ color: number; label: string; count: number }>;
};

export function DanmakuColorList({ colors }: DanmakuColorListProps) {
  if (!colors.length) {
    return <div className="p-6 text-center text-sm text-muted">暂无颜色数据</div>;
  }

  const total = Math.max(1, colors.reduce((sum, color) => sum + color.count, 0));
  return (
    <div className="space-y-3">
      {colors.slice(0, 8).map((item) => (
        <div className="flex items-center justify-between gap-3" key={item.color}>
          <div className="flex min-w-0 items-center gap-3">
            <span
              className="h-6 w-6 shrink-0 rounded border border-line"
              style={{ backgroundColor: colorNumberToHex(item.color) }}
            />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-ink">{item.label}</div>
              <div className="text-xs text-muted">{formatNumber(item.count)} 条</div>
            </div>
          </div>
          <span className="rounded bg-white/72 px-2 py-1 text-sm font-medium text-muted shadow-sm">
            {Math.round((item.count / total) * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}

type RepeatedDanmakuListProps = {
  items: Array<{ content: string; count: number; sample: DanmakuItem }>;
  onSelect: (item: { content: string; count: number; sample: DanmakuItem }) => void;
};

export function RepeatedDanmakuList({ items, onSelect }: RepeatedDanmakuListProps) {
  if (!items.length) {
    return <div className="p-6 text-center text-sm text-muted">暂无重复内容</div>;
  }

  return (
    <div className="grid gap-2 md:grid-cols-2">
      {items.slice(0, 8).map((item) => (
        <button
          className="interactive-card min-h-20 rounded-md border border-line bg-white/70 p-3 text-left transition hover:border-bilibili hover:bg-white"
          key={`${item.content}-${item.sample.dmid}`}
          type="button"
          onClick={() => onSelect(item)}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="line-clamp-1 min-w-0 text-sm font-semibold text-ink">{item.content}</span>
            <span className="shrink-0 rounded bg-amber-50 px-2 py-1 text-sm font-semibold text-amber">
              {formatNumber(item.count)}
            </span>
          </div>
          <div className="mt-2 text-xs text-muted">样本时间 {formatProgress(item.sample.progress)}</div>
        </button>
      ))}
    </div>
  );
}

export { ColorSwatch };
