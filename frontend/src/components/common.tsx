import { RefreshCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { formatNumber } from "../lib/utils";
import type { ProgressState } from "../types";

type MetricProps = {
  icon: LucideIcon;
  label: string;
  value?: number;
};

export function Metric({ icon: Icon, label, value }: MetricProps) {
  return (
    <span className="inline-flex h-8 items-center gap-1 rounded-md border border-line bg-[#fbfcfe] px-2.5 text-sm">
      <Icon size={15} aria-hidden="true" />
      {label} {formatNumber(value)}
    </span>
  );
}

type PanelProps = {
  icon: LucideIcon;
  title: string;
  action?: string;
  children: ReactNode;
};

export function Panel({ icon: Icon, title, action, children }: PanelProps) {
  return (
    <section className="min-w-0 overflow-hidden rounded-md border border-line bg-white shadow-soft">
      <div className="flex min-h-14 items-center justify-between border-b border-line px-4">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <Icon size={18} aria-hidden="true" />
          {title}
        </h2>
        {action && <span className="text-sm text-muted">{action}</span>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

type ProgressBannerProps = {
  progress: ProgressState | null;
  fallback: string;
};

export function ProgressBanner({ progress, fallback }: ProgressBannerProps) {
  const logs = progress?.logs?.slice(-4) || [];
  const percent = Math.max(0, Math.min(100, Math.round(progress?.percent ?? 8)));
  const stage = progress?.stage || "准备中";
  const stats = selectProgressStats(progress?.stage || "", progress?.stats || {});
  return (
    <section className="border-b border-amber-100 bg-[#fff8e7]">
      <div className="mx-auto max-w-[1540px] px-4 py-3 text-sm text-[#5f4612] lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 font-semibold text-ink">
              <RefreshCcw className="animate-spin text-amber" size={16} aria-hidden="true" />
              <span>{stage}</span>
              <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-[#6b4b13]">{percent}%</span>
            </div>
            <div className="mt-1 truncate text-sm text-[#6b4b13]">{progress?.message || fallback}</div>
          </div>
          {stats.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {stats.map(([label, value]) => (
                <span className="rounded-md border border-amber-100 bg-white px-2.5 py-1 text-xs" key={label}>
                  {label} <strong className="text-ink">{value}</strong>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
          <div className="h-full rounded-full bg-amber transition-all duration-300" style={{ width: `${percent}%` }} />
        </div>

        {logs.length > 0 && (
          <div className="mt-2 grid gap-1 text-xs text-[#7a5a1a]">
            {logs.map((item, index) => (
              <div className="flex min-w-0 items-center gap-2" key={`${item}-${index}`}>
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" />
                <span className="truncate">{item}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function selectProgressStats(stage: string, stats: ProgressState["stats"]) {
  const entries = Object.entries(stats);
  const preferred =
    stage === "抓取楼中楼"
      ? ["楼中楼进度", "当前根评论", "当前楼中楼预期", "楼中楼已抓", "楼中楼预期"]
      : stage === "抓取主评论"
        ? ["主评论页", "本页评论", "已抓评论", "接口总数"]
        : stage === "弹幕点赞"
          ? ["点赞批次", "本批 dmid", "弹幕条数"]
          : ["弹幕条数", "主评论页", "已抓评论", "接口总数"];

  const ordered = [
    ...preferred
      .filter((label) => Object.prototype.hasOwnProperty.call(stats, label))
      .map((label) => [label, stats[label]] as [string, string | number]),
    ...entries.filter(([label]) => !preferred.includes(label)),
  ];

  return ordered.slice(0, 6);
}

type InfoRowProps = {
  label: string;
  value: string;
};

export function InfoRow({ label, value }: InfoRowProps) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 rounded bg-[#fbfcfe] px-3 py-2">
      <dt className="text-muted">{label}</dt>
      <dd className="break-all font-mono text-xs text-ink">{value}</dd>
    </div>
  );
}

type DetailMetricProps = {
  icon: LucideIcon;
  label: string;
  value: number | string;
};

export function DetailMetric({ icon: Icon, label, value }: DetailMetricProps) {
  return (
    <div className="rounded-md border border-line bg-[#fbfcfe] p-3">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Icon size={14} aria-hidden="true" />
        {label}
      </div>
      <div className="mt-2 break-words text-sm font-semibold text-ink">{value}</div>
    </div>
  );
}

export function OwnerBadge() {
  return (
    <span className="inline-flex shrink-0 items-center rounded border border-bilibili/25 bg-pink-50 px-1.5 py-0.5 text-xs font-medium text-bilibili">
      UP主
    </span>
  );
}
