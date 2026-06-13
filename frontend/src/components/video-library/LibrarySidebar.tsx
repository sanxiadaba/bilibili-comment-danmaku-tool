import { AlertTriangle, FolderOpen, LinkIcon, PlusCircle, RefreshCcw, Users } from "lucide-react";
import type React from "react";
import { InfoRow } from "../common";
import { cn, formatNumber } from "../../lib/utils";
import type { CookieStatus, DatabaseInfo, VideoSummary } from "../../types";
import { OwnerFilterButton } from "./OwnerFilterButton";
import type { OwnerGroup } from "./types";

type LibrarySidebarProps = {
  activeDatabase?: DatabaseInfo;
  cookieStatus?: CookieStatus | null;
  duplicateVideo: VideoSummary | null;
  exportingKey: string;
  hasSpaceQueueWork: boolean;
  hotplugDir: string;
  isParsing: boolean;
  isSubmittingSpace: boolean;
  isTaskBusy: boolean;
  ownerFilter: string;
  ownerGroups: OwnerGroup[];
  ownerRef: string;
  parseDelay: number;
  showSettings: boolean;
  totals: {
    comments: number;
    danmaku: number;
  };
  url: string;
  videoCount: number;
  onDuplicateOpen: (video: VideoSummary) => void;
  onDuplicateReparse: () => void;
  onOwnerDelete: (owner: OwnerGroup) => void;
  onOwnerExport: (owner: OwnerGroup) => void;
  onOwnerFilterChange: (ownerKey: string, owner?: OwnerGroup) => void;
  onOwnerRefChange: (value: string) => void;
  onParseDelayChange: (value: number) => void;
  onSubmitParse: (event: React.FormEvent<HTMLFormElement>) => void;
  onSubmitSpaceArchive: (event: React.FormEvent<HTMLFormElement>) => void;
  onUrlChange: (value: string) => void;
};

export function LibrarySidebar({
  activeDatabase,
  cookieStatus,
  duplicateVideo,
  exportingKey,
  hasSpaceQueueWork,
  hotplugDir,
  isParsing,
  isSubmittingSpace,
  isTaskBusy,
  ownerFilter,
  ownerGroups,
  ownerRef,
  parseDelay,
  showSettings,
  totals,
  url,
  videoCount,
  onDuplicateOpen,
  onDuplicateReparse,
  onOwnerDelete,
  onOwnerExport,
  onOwnerFilterChange,
  onOwnerRefChange,
  onParseDelayChange,
  onSubmitParse,
  onSubmitSpaceArchive,
  onUrlChange,
}: LibrarySidebarProps) {
  return (
    <aside className="surface-card self-start rounded-md p-4">
      <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
        <PlusCircle size={18} aria-hidden="true" />
        解析新视频
      </h2>
      <form className="mt-4 grid gap-3" onSubmit={onSubmitParse}>
        <label className="grid gap-2 text-sm text-muted">
          视频链接或 BV 号
          <span className="input-shell flex h-11 min-w-0 items-center gap-2 rounded-md px-3">
            <LinkIcon size={16} aria-hidden="true" />
            <input
              className="min-w-0 flex-1 bg-transparent text-ink outline-none"
              placeholder="https://www.bilibili.com/video/BV..."
              value={url}
              onChange={(event) => onUrlChange(event.target.value)}
            />
          </span>
        </label>
        <button
          className="btn-primary inline-flex h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
          type="submit"
          disabled={isTaskBusy}
        >
          <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
          {isParsing ? "解析中" : "解析视频"}
        </button>
      </form>
      {duplicateVideo && (
        <DuplicateVideoNotice
          disabled={isTaskBusy}
          isParsing={isParsing}
          video={duplicateVideo}
          onOpen={() => onDuplicateOpen(duplicateVideo)}
          onReparse={onDuplicateReparse}
        />
      )}
      <div className="mt-4 border-t border-line pt-4">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <Users size={18} aria-hidden="true" />
          抓取UP主
        </h2>
        <form className="mt-4 grid gap-3" onSubmit={onSubmitSpaceArchive}>
          <label className="grid gap-2 text-sm text-muted">
            UP 主主页或 mid
            <span className="input-shell flex h-11 min-w-0 items-center gap-2 rounded-md px-3">
              <LinkIcon size={16} aria-hidden="true" />
              <input
                className="min-w-0 flex-1 bg-transparent text-ink outline-none"
                placeholder="https://space.bilibili.com/123456"
                value={ownerRef}
                onChange={(event) => onOwnerRefChange(event.target.value)}
              />
            </span>
          </label>
          <button
            className="btn-accent inline-flex h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
            type="submit"
            disabled={isSubmittingSpace}
          >
            <RefreshCcw className={cn((isSubmittingSpace || hasSpaceQueueWork) && "animate-spin")} size={16} aria-hidden="true" />
            {isSubmittingSpace ? "加入队列中" : "抓取全部视频"}
          </button>
        </form>
      </div>
      {showSettings && (
        <div className="mt-4 grid gap-3 border-t border-line pt-4">
          <label className="grid gap-2 text-sm text-muted">
            抓取延迟
            <span className="input-shell flex h-10 items-center gap-3 rounded-md px-3">
              <input
                className="min-w-0 flex-1 accent-bilibili"
                max={2}
                min={0}
                step={0.05}
                type="range"
                value={parseDelay}
                onChange={(event) => onParseDelayChange(Number(event.target.value))}
              />
              <span className="w-14 text-right font-medium text-ink">{parseDelay.toFixed(2)}s</span>
            </span>
          </label>
          <div className="grid gap-2 text-sm">
            <CookieStatusRow status={cookieStatus} />
            <InfoRow label="当前数据库" value={activeDatabase?.relative_path || "data/comment_danmaku.db"} />
            <InfoRow label="热插拔目录" value={hotplugDir} />
          </div>
        </div>
      )}
      <OwnerFilterList
        exportingKey={exportingKey}
        ownerFilter={ownerFilter}
        ownerGroups={ownerGroups}
        totals={totals}
        videoCount={videoCount}
        onExport={onOwnerExport}
        onDelete={onOwnerDelete}
        onSelect={onOwnerFilterChange}
      />
    </aside>
  );
}

function CookieStatusRow({ status }: { status?: CookieStatus | null }) {
  const tone =
    status?.status === "valid"
      ? "text-emerald-700"
      : status?.status === "invalid" || status?.status === "error"
        ? "text-red-700"
        : "text-muted";
  const label = status
    ? [
        status.is_login ? "登录有效" : status.exists ? "未登录" : "未找到",
        status.has_sessdata ? "SESSDATA" : "",
        status.has_dede_user_id ? "DedeUserID" : "",
        status.bili_ticket_expired ? "短期票据过期" : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "检测中";

  return (
    <div className="flex min-w-0 items-start justify-between gap-3">
      <span className="shrink-0 text-muted">Cookie</span>
      <span className={cn("min-w-0 text-right", tone)} title={status?.message || "data/cookie.txt"}>
        {label}
      </span>
    </div>
  );
}

type DuplicateVideoNoticeProps = {
  disabled: boolean;
  isParsing: boolean;
  video: VideoSummary;
  onOpen: () => void;
  onReparse: () => void;
};

function DuplicateVideoNotice({ disabled, isParsing, video, onOpen, onReparse }: DuplicateVideoNoticeProps) {
  return (
    <div className="mt-4 grid gap-3 rounded-md border border-amber-200 bg-amber-50/88 p-3 text-sm text-ink shadow-sm">
      <div className="flex min-w-0 items-start gap-2">
        <AlertTriangle className="mt-0.5 shrink-0 text-amber-600" size={17} aria-hidden="true" />
        <div className="min-w-0">
          <div className="font-medium text-amber-900">该视频已在本地档案中</div>
          <div className="mt-1 line-clamp-2 text-amber-800">{video.title}</div>
          <div className="mt-1 text-xs text-amber-700">
            {video.bvid} · 档案 {formatNumber(video.comment_total_count)} · 弹幕 {formatNumber(video.danmaku_count)}
          </div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <button
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 transition hover:border-amber-500 hover:shadow-sm"
          type="button"
          onClick={onOpen}
        >
          <FolderOpen size={16} aria-hidden="true" />
          打开已有档案
        </button>
        <button
          className="btn-primary inline-flex h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
          type="button"
          disabled={disabled}
          onClick={onReparse}
        >
          <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
          重新抓取
        </button>
      </div>
    </div>
  );
}

type OwnerFilterListProps = {
  exportingKey: string;
  ownerFilter: string;
  ownerGroups: OwnerGroup[];
  totals: {
    comments: number;
    danmaku: number;
  };
  videoCount: number;
  onExport: (owner: OwnerGroup) => void;
  onDelete: (owner: OwnerGroup) => void;
  onSelect: (ownerKey: string, owner?: OwnerGroup) => void;
};

function OwnerFilterList({
  exportingKey,
  ownerFilter,
  ownerGroups,
  totals,
  videoCount,
  onExport,
  onDelete,
  onSelect,
}: OwnerFilterListProps) {
  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <Users size={18} aria-hidden="true" />
          UP主分类
        </h2>
        <span className="text-xs text-muted">{ownerGroups.length} 位</span>
      </div>
      <div className="mt-3 grid gap-2">
        <OwnerFilterButton
          active={ownerFilter === "all"}
          commentCount={totals.comments}
          danmakuCount={totals.danmaku}
          name="全部视频"
          videoCount={videoCount}
          onClick={() => onSelect("all")}
        />
        <div className="max-h-[360px] overflow-y-auto pr-1">
          <div className="grid gap-2">
            {ownerGroups.map((owner) => (
              <OwnerFilterButton
                active={ownerFilter === owner.key}
                commentCount={owner.commentCount}
                danmakuCount={owner.danmakuCount}
                exportDisabled={Boolean(exportingKey)}
                exporting={exportingKey === `owner:${owner.key}`}
                key={owner.key}
                name={owner.name}
                videoCount={owner.videoCount}
                onExport={() => onExport(owner)}
                onDelete={() => onDelete(owner)}
                onClick={() => onSelect(owner.key, owner)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
