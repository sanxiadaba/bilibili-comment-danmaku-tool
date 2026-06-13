import { ThumbsUp } from "lucide-react";
import type { CommentNode } from "../../types";
import { cleanIpLocation, formatDateTime, normalizeImageUrl } from "../../lib/utils";
import { Avatar } from "../ui/Avatar";
import { getBilibiliUserUrl } from "./commentUtils";

type TimeChartProps = {
  allBuckets: Array<{ label: string; count: number; timestamp: number }>;
  filteredBuckets: Array<{ label: string; count: number; timestamp: number }>;
};

export function TimeChart({ allBuckets, filteredBuckets }: TimeChartProps) {
  const filteredByTime = new Map(filteredBuckets.map((bucket) => [bucket.timestamp, bucket.count]));
  const max = Math.max(1, ...allBuckets.map((bucket) => bucket.count));
  const chartWidth = Math.max(520, allBuckets.length * 16);

  if (!allBuckets.length) {
    return (
      <div className="surface-muted grid min-h-56 place-items-center rounded-md border-dashed p-6 text-center text-sm text-muted">
        暂无可绘制的评论时间数据
      </div>
    );
  }

  return (
    <div className="min-w-0 w-full max-w-full">
      <div className="overflow-x-auto overflow-y-hidden pb-2">
        <div className="h-64" style={{ width: `${chartWidth}px` }}>
          <div className="flex h-56 items-end gap-1 border-b border-line">
            {allBuckets.map((bucket) => {
              const filteredCount = filteredByTime.get(bucket.timestamp) || 0;
              return (
                <div
                  className="group flex h-full min-w-3 flex-1 flex-col items-center justify-end gap-1"
                  key={bucket.timestamp}
                  title={`${bucket.label}：全部 ${bucket.count} 条，筛选 ${filteredCount} 条`}
                >
                  <div className="relative flex h-52 w-full items-end rounded-t bg-slate-100">
                    <div
                      className="w-full rounded-t bg-cyan/35"
                      style={{ height: `${Math.max(6, (bucket.count / max) * 100)}%` }}
                    />
                    <div
                      className="absolute bottom-0 w-full rounded-t bg-bilibili"
                      style={{ height: filteredCount ? `${Math.max(6, (filteredCount / max) * 100)}%` : 0 }}
                    />
                  </div>
                  <span className="hidden text-[10px] text-muted group-hover:block">{bucket.count}</span>
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex min-w-0 items-center justify-between gap-3 text-xs text-muted">
            <span className="min-w-0 truncate">{allBuckets[0]?.label}</span>
            <span className="inline-flex shrink-0 items-center gap-3">
              <span className="inline-flex items-center gap-1">
                <i className="h-2.5 w-2.5 rounded-sm bg-cyan/35" />
                全部
              </span>
              <span className="inline-flex items-center gap-1">
                <i className="h-2.5 w-2.5 rounded-sm bg-bilibili" />
                筛选
              </span>
            </span>
            <span className="min-w-0 truncate text-right">{allBuckets.at(-1)?.label}</span>
          </div>
        </div>
      </div>
      <div className="mt-1 flex justify-between gap-3 text-xs text-muted">
        <span>共 {allBuckets.length} 个时间段</span>
        <span>可横向滚动查看完整时间线</span>
      </div>
    </div>
  );
}

type LocationChartProps = {
  locations: Array<{ label: string; count: number }>;
  total: number;
};

export function LocationChart({ locations, total }: LocationChartProps) {
  const max = Math.max(1, ...locations.map((item) => item.count));
  return (
    <div className="space-y-3">
      {locations.map((item) => (
        <div className="grid grid-cols-[72px_minmax(0,1fr)_44px] items-center gap-3 text-sm" key={item.label}>
          <span className="truncate font-medium text-ink">{item.label}</span>
          <div className="h-3 overflow-hidden rounded-sm bg-slate-100">
            <div className="h-full rounded-sm bg-mint" style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <span className="text-right text-muted">{Math.round((item.count / total) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

type AuthorListProps = {
  authors: Array<{ name: string; mid: string; count: number; likes: number; avatar?: string }>;
};

export function AuthorList({ authors }: AuthorListProps) {
  return (
    <div className="space-y-3">
      {authors.map((author) => (
        <div className="flex items-center justify-between gap-3" key={author.mid || author.name}>
          <div className="flex min-w-0 items-center gap-3">
            <Avatar name={author.name} size="md" src={normalizeImageUrl(author.avatar)} href={getBilibiliUserUrl(author.mid)} />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-ink">{author.name}</div>
              <div className="text-xs text-muted">{author.count} 条评论</div>
            </div>
          </div>
          <span className="inline-flex items-center gap-1 rounded bg-pink-50 px-2 py-1 text-sm font-semibold text-bilibili">
            <ThumbsUp size={13} aria-hidden="true" />
            {author.likes}
          </span>
        </div>
      ))}
    </div>
  );
}

export type LikedComment = CommentNode;
