import { Download, FolderOpen, RefreshCcw, Settings, Upload } from "lucide-react";
import type React from "react";
import { InfoRow } from "../common";
import { cn, formatNumber } from "../../lib/utils";
import { formatBytes } from "../../lib/videoLibrary";
import type { DatabaseInfo } from "../../types";

type ManagementPanelProps = {
  activeDbId: string;
  databases: DatabaseInfo[];
  hotplugDir: string;
  importPath: string;
  isImporting: boolean;
  isLoading: boolean;
  onImportPathChange: (value: string) => void;
  onPickFiles: () => void;
  onPickFolder: () => void;
  onRefresh: () => void;
  onSelect: (dbId: string) => void;
  onSubmitImport: (event: React.FormEvent<HTMLFormElement>) => void;
};

export function ManagementPanel({
  activeDbId,
  databases,
  hotplugDir,
  importPath,
  isImporting,
  isLoading,
  onImportPathChange,
  onPickFiles,
  onPickFolder,
  onRefresh,
  onSelect,
  onSubmitImport,
}: ManagementPanelProps) {
  const activeDatabase = databases.find((database) => database.id === activeDbId);
  const healthyCount = databases.filter((database) => database.ok).length;
  const activeDatabaseName = activeDatabase?.name || (activeDbId === "main" ? "全部视频" : activeDbId);

  return (
    <section className="surface-card rounded-md">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/80 bg-white/42 px-4 py-3">
        <div className="min-w-0">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <Settings size={18} aria-hidden="true" />
            管理工具
          </h2>
          <div className="mt-1 text-sm text-muted">
            数据库 {healthyCount}/{databases.length} 可用
          </div>
        </div>
      </div>
      <DatabaseManagerPanel
        activeDatabaseName={activeDatabaseName}
        activeDbId={activeDbId}
        databases={databases}
        healthyCount={healthyCount}
        hotplugDir={hotplugDir}
        importPath={importPath}
        isImporting={isImporting}
        isLoading={isLoading}
        onImportPathChange={onImportPathChange}
        onPickFiles={onPickFiles}
        onPickFolder={onPickFolder}
        onRefresh={onRefresh}
        onSelect={onSelect}
        onSubmitImport={onSubmitImport}
      />
    </section>
  );
}

type DatabaseManagerPanelProps = {
  activeDatabaseName: string;
  activeDbId: string;
  databases: DatabaseInfo[];
  healthyCount: number;
  hotplugDir: string;
  importPath: string;
  isImporting: boolean;
  isLoading: boolean;
  onImportPathChange: (value: string) => void;
  onPickFiles: () => void;
  onPickFolder: () => void;
  onRefresh: () => void;
  onSelect: (dbId: string) => void;
  onSubmitImport: (event: React.FormEvent<HTMLFormElement>) => void;
};

function DatabaseManagerPanel({
  activeDatabaseName,
  activeDbId,
  databases,
  healthyCount,
  hotplugDir,
  importPath,
  isImporting,
  isLoading,
  onImportPathChange,
  onPickFiles,
  onPickFolder,
  onRefresh,
  onSelect,
  onSubmitImport,
}: DatabaseManagerPanelProps) {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/80 px-4 py-3">
        <div className="min-w-0 text-sm text-muted">
          {databases.length} 个已发现 · {healthyCount} 个可用 · 当前 {activeDatabaseName}
        </div>
        <button
          className="btn-quiet inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
          type="button"
          disabled={isLoading}
          onClick={onRefresh}
        >
          <RefreshCcw className={cn(isLoading && "animate-spin")} size={16} aria-hidden="true" />
          扫描文件夹
        </button>
      </div>

      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          <div className="grid gap-2 text-sm">
            <InfoRow label="视频数据库目录" value={hotplugDir} />
          </div>
          <div className="mt-3 grid max-h-[290px] gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
            {databases.map((database) => (
              <DatabaseCard active={database.id === activeDbId} database={database} key={database.id} onSelect={() => onSelect(database.id)} />
            ))}
            {!isLoading && databases.length === 0 && <div className="surface-muted rounded-md border-dashed p-4 text-sm text-muted">没有发现数据库</div>}
          </div>
        </div>

        <form className="surface-muted grid content-start gap-3 rounded-md p-3" onSubmit={onSubmitImport}>
          <div>
            <div className="text-sm font-semibold text-ink">导入已有数据库</div>
            <div className="mt-1 text-xs text-muted">可导入 .db/.sqlite/.sqlite3 或导出的 JSON 数据文件。</div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
              type="button"
              disabled={isImporting}
              onClick={onPickFiles}
            >
              <Upload size={16} aria-hidden="true" />
              选择文件
            </button>
            <button
              className="btn-quiet inline-flex h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
              type="button"
              disabled={isImporting}
              onClick={onPickFolder}
            >
              <FolderOpen size={16} aria-hidden="true" />
              选择文件夹
            </button>
          </div>
          <label className="grid gap-2 text-sm text-muted">
            本机路径导入
            <span className="input-shell flex h-10 min-w-0 items-center gap-2 rounded-md px-3">
              <FolderOpen size={16} aria-hidden="true" />
              <input className="min-w-0 flex-1 bg-transparent text-ink outline-none" placeholder="D:\\backups\\archive.db 或 archive.json" value={importPath} onChange={(event) => onImportPathChange(event.target.value)} />
            </span>
          </label>
          <button
            className="btn-primary inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:cursor-wait disabled:opacity-70"
            type="submit"
            disabled={isImporting}
          >
            <Download className={cn(isImporting && "animate-bounce")} size={16} aria-hidden="true" />
            {isImporting ? "导入中" : "导入并切换"}
          </button>
        </form>
      </div>
    </div>
  );
}

function DatabaseCard({ active, database, onSelect }: { active: boolean; database: DatabaseInfo; onSelect: () => void }) {
  const roleLabel = "视频库";
  const kindLabel = databaseKindLabel(database.archive_kind);
  const coverageTone =
    database.coverage_status === "has_better"
      ? "text-amber-700"
      : database.coverage_status === "duplicate"
        ? "text-cyan-700"
        : database.coverage_status === "overlap"
          ? "text-muted"
          : "text-emerald-700";

  return (
    <button
      className={cn(
        "interactive-card grid min-w-0 gap-2 rounded-md border p-3 text-left transition",
        active ? "border-bilibili bg-pink-50/90 shadow-sm" : "border-line bg-white/70 hover:border-bilibili hover:bg-white",
        !database.ok && "border-amber-200 bg-amber-50",
      )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-ink">{database.name}</div>
          <div className="mt-0.5 truncate text-xs text-muted">{database.file_name}</div>
        </div>
        <span className="shrink-0 rounded bg-white px-2 py-0.5 text-xs text-muted">{roleLabel}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1 text-xs">
        <span className="rounded bg-white px-2 py-0.5 text-muted">{kindLabel}</span>
        {database.owner_name && <span className="rounded bg-white px-2 py-0.5 text-muted">UP {database.owner_name}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <span>视频 {formatNumber(database.video_count)}</span>
        <span>评论 {formatNumber(database.comment_count)}</span>
        <span>弹幕 {formatNumber(database.danmaku_count)}</span>
        <span>{formatBytes(database.size_bytes)}</span>
      </div>
      {database.ok && (
        <div className="rounded-md bg-white/70 px-2.5 py-2 text-xs text-muted">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>实际占用 {formatBytes(database.used_bytes || database.size_bytes)}</span>
            <span>可回收 {formatBytes(database.reclaimable_bytes || 0)}</span>
            {database.wal_bytes > 0 && <span>临时日志 {formatBytes(database.wal_bytes)}</span>}
          </div>
          {database.storage_message && <div className="mt-1 line-clamp-2 text-[11px] leading-5">{database.storage_message}</div>}
          {database.top_owners?.length > 0 && (
            <div className="mt-2 grid gap-1">
              {database.top_owners.slice(0, 3).map((owner) => (
                <div className="flex min-w-0 items-center justify-between gap-2" key={`${owner.owner_mid}:${owner.owner_name}`}>
                  <span className="truncate text-ink">{owner.owner_name || owner.owner_mid || "未知UP主"}</span>
                  <span className="shrink-0 text-muted">
                    {formatNumber(owner.video_count)} 视频 · {formatNumber(owner.comment_count)} 评论 · {formatNumber(owner.danmaku_count)} 弹幕
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {database.coverage_message && <div className={cn("line-clamp-2 text-xs", coverageTone)}>{database.coverage_message}</div>}
      <div className={cn("truncate text-xs", database.ok ? "text-muted" : "text-amber-700")}>{database.ok ? database.relative_path : database.error || "不可用"}</div>
    </button>
  );
}

function databaseKindLabel(kind: string) {
  if (kind === "up") return "UP 主库";
  if (kind === "video") return "单视频库";
  if (kind === "collection") return "视频集合";
  return "未标注";
}
