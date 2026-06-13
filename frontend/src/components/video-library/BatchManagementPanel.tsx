import { Database, Download, Search, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { cn, formatNumber } from "../../lib/utils";
import { formatBytes } from "../../lib/videoLibrary";
import type { VideoSummary } from "../../types";
import type { ExportFormat, OwnerGroup } from "./types";

type BatchManagementPanelProps = {
  disabled: boolean;
  ownerGroups: OwnerGroup[];
  videos: VideoSummary[];
  onDeleteOwners: (owners: OwnerGroup[]) => void;
  onDeleteVideos: (videos: VideoSummary[]) => void;
  onExportOwners: (owners: OwnerGroup[], format: ExportFormat) => void;
  onExportVideos: (videos: VideoSummary[], format: ExportFormat) => void;
};

type Mode = "owners" | "videos";

export function BatchManagementPanel({
  disabled,
  ownerGroups,
  videos,
  onDeleteOwners,
  onDeleteVideos,
  onExportOwners,
  onExportVideos,
}: BatchManagementPanelProps) {
  const [mode, setMode] = useState<Mode>("owners");
  const [query, setQuery] = useState("");
  const [selectedOwners, setSelectedOwners] = useState<Set<string>>(() => new Set());
  const [selectedVideos, setSelectedVideos] = useState<Set<string>>(() => new Set());
  const needle = query.trim().toLowerCase();
  const filteredOwners = useMemo(
    () =>
      ownerGroups.filter((owner) =>
        [owner.name, owner.ownerMid].some((value) => value.toLowerCase().includes(needle)),
      ),
    [needle, ownerGroups],
  );
  const filteredVideos = useMemo(
    () =>
      videos.filter((video) =>
        [video.title, video.bvid, video.owner_name || ""].some((value) => value.toLowerCase().includes(needle)),
      ),
    [needle, videos],
  );
  const owners = ownerGroups.filter((owner) => selectedOwners.has(owner.key));
  const selectedVideoRows = videos.filter((video) => selectedVideos.has(video.bvid));
  const selectedCount = mode === "owners" ? owners.length : selectedVideoRows.length;

  return (
    <section className="surface-card mx-auto grid max-w-[1540px] gap-4 rounded-md px-4 py-4 lg:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">批量管理</h2>
          <div className="mt-1 text-sm text-muted">集中处理导出和删除，视频列表保持清爽。</div>
        </div>
        <div className="inline-flex rounded-md border border-line bg-[#f6f9fc]/90 p-1">
          <ModeButton active={mode === "owners"} icon={Users} label="UP主" onClick={() => setMode("owners")} />
          <ModeButton active={mode === "videos"} icon={Database} label="视频" onClick={() => setMode("videos")} />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="input-shell flex h-10 min-w-[260px] flex-1 items-center gap-2 rounded-md px-3 text-sm text-muted">
          <Search size={16} aria-hidden="true" />
          <input
            className="min-w-0 flex-1 bg-transparent text-ink outline-none"
            placeholder={mode === "owners" ? "搜索 UP 名称或 mid" : "搜索标题、UP 或 BV"}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button className="btn-quiet h-10 rounded-md px-3 text-sm font-medium" type="button" onClick={() => (mode === "owners" ? setSelectedOwners(new Set(filteredOwners.map((owner) => owner.key))) : setSelectedVideos(new Set(filteredVideos.map((video) => video.bvid))))}>
            全选当前
          </button>
          <button className="btn-quiet h-10 rounded-md px-3 text-sm font-medium" type="button" onClick={() => (mode === "owners" ? setSelectedOwners(new Set()) : setSelectedVideos(new Set()))}>
            清空
          </button>
        </div>
      </div>

      <div className="grid gap-2">
        {(mode === "owners" ? filteredOwners : filteredVideos).map((item) =>
          mode === "owners" ? (
            <OwnerBatchRow
              key={(item as OwnerGroup).key}
              owner={item as OwnerGroup}
              selected={selectedOwners.has((item as OwnerGroup).key)}
              onToggle={() => setSelectedOwners(toggleSet(selectedOwners, (item as OwnerGroup).key))}
            />
          ) : (
            <VideoBatchRow
              key={(item as VideoSummary).bvid}
              video={item as VideoSummary}
              selected={selectedVideos.has((item as VideoSummary).bvid)}
              onToggle={() => setSelectedVideos(toggleSet(selectedVideos, (item as VideoSummary).bvid))}
            />
          ),
        )}
      </div>

      <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-white/95 p-3 shadow-lg backdrop-blur">
        <div className="text-sm text-muted">已选择 {selectedCount} 项</div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-quiet inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium" type="button" disabled={disabled || selectedCount === 0} onClick={() => (mode === "owners" ? onExportOwners(owners, "sqlite") : onExportVideos(selectedVideoRows, "sqlite"))}>
            <Database size={16} aria-hidden="true" />
            导出 SQLite
          </button>
          <button className="btn-quiet inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium" type="button" disabled={disabled || selectedCount === 0} onClick={() => (mode === "owners" ? onExportOwners(owners, "json") : onExportVideos(selectedVideoRows, "json"))}>
            <Download size={16} aria-hidden="true" />
            导出 JSON
          </button>
          <button className="inline-flex h-10 items-center gap-2 rounded-md bg-red-600 px-3 text-sm font-medium text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60" type="button" disabled={disabled || selectedCount === 0} onClick={() => (mode === "owners" ? onDeleteOwners(owners) : onDeleteVideos(selectedVideoRows))}>
            <Trash2 size={16} aria-hidden="true" />
            批量删除
          </button>
        </div>
      </div>
    </section>
  );
}

function ModeButton({ active, icon: Icon, label, onClick }: { active: boolean; icon: typeof Users; label: string; onClick: () => void }) {
  return (
    <button className={cn("inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium", active ? "bg-white text-ink shadow-sm ring-1 ring-line" : "text-muted hover:bg-white hover:text-ink")} type="button" onClick={onClick}>
      <Icon size={16} aria-hidden="true" />
      {label}
    </button>
  );
}

function OwnerBatchRow({ owner, selected, onToggle }: { owner: OwnerGroup; selected: boolean; onToggle: () => void }) {
  return (
    <label className="interactive-card grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-md border border-line bg-white/72 p-3">
      <input className="mt-1 accent-bilibili" type="checkbox" checked={selected} onChange={onToggle} />
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-ink">{owner.name}</span>
          <span className="rounded bg-[#eef3f8] px-2 py-0.5 text-xs text-muted">{owner.ownerMid || "无 mid"}</span>
        </span>
        <span className="mt-1 block text-xs text-muted">
          {formatNumber(owner.videoCount)} 视频 · {formatNumber(owner.commentCount)} 评论 · {formatNumber(owner.danmakuCount)} 弹幕 · 估算 {formatBytes(owner.storageBytes || 0)}
        </span>
      </span>
    </label>
  );
}

function VideoBatchRow({ video, selected, onToggle }: { video: VideoSummary; selected: boolean; onToggle: () => void }) {
  return (
    <label className="interactive-card grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-md border border-line bg-white/72 p-3">
      <input className="mt-1 accent-bilibili" type="checkbox" checked={selected} onChange={onToggle} />
      <span className="min-w-0">
        <span className="line-clamp-2 font-medium text-ink">{video.title}</span>
        <span className="mt-1 block text-xs text-muted">
          {video.bvid} · {video.owner_name || "UP主"} · {formatNumber(video.comment_total_count)} 评论 · {formatNumber(video.danmaku_count)} 弹幕
        </span>
      </span>
    </label>
  );
}

function toggleSet(current: Set<string>, key: string) {
  const next = new Set(current);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  return next;
}
