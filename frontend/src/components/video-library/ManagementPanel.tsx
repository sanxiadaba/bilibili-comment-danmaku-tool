import { Database, Download, FolderOpen, KeyRound, RefreshCcw, Settings, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type React from "react";
import { InfoRow } from "../common";
import { cn, formatNumber } from "../../lib/utils";
import { formatBytes } from "../../lib/videoLibrary";
import type { CookieStatus, DatabaseInfo, ProgressQueue } from "../../types";
import { AuthPanel } from "./AuthPanel";
import { ProgressQueuePanel } from "./ProgressQueuePanel";
import type { ManagementView } from "./types";

const AUTH_TAB_LABEL = "\u767b\u5f55\u6001";
const AUTH_LABEL_VALID = "\u5df2\u767b\u5f55";
const AUTH_LABEL_STALE = "\u5f85\u66f4\u65b0";
const AUTH_LABEL_MISSING = "\u672a\u914d\u7f6e";

type ManagementPanelProps = {
  activeDbId: string;
  cookieStatus?: CookieStatus | null;
  databases: DatabaseInfo[];
  hotplugDir: string;
  importPath: string;
  isImporting: boolean;
  isLoading: boolean;
  legacyExportDir: string;
  queue?: ProgressQueue;
  view: ManagementView;
  onCookieStatusChange?: (status: CookieStatus | null) => void;
  onImportPathChange: (value: string) => void;
  onPickFiles: () => void;
  onPickFolder: () => void;
  onRefresh: () => void;
  onSelect: (dbId: string) => void;
  onViewChange: (view: ManagementView) => void;
  onSubmitImport: (event: React.FormEvent<HTMLFormElement>) => void;
};

export function ManagementPanel({
  activeDbId,
  cookieStatus,
  databases,
  hotplugDir,
  importPath,
  isImporting,
  isLoading,
  legacyExportDir,
  queue,
  view,
  onCookieStatusChange,
  onImportPathChange,
  onPickFiles,
  onPickFolder,
  onRefresh,
  onSelect,
  onViewChange,
  onSubmitImport,
}: ManagementPanelProps) {
  const queuedCount = queue?.queued?.length || 0;
  const hasActiveTask = Boolean(queue?.active);
  const activeDatabase = databases.find((database) => database.id === activeDbId);
  const healthyCount = databases.filter((database) => database.ok).length;
  const authLabel = cookieStatus?.is_login ? AUTH_LABEL_VALID : cookieStatus?.exists ? AUTH_LABEL_STALE : AUTH_LABEL_MISSING;

  return (
    <section className="rounded-md border border-line bg-white shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <Settings size={18} aria-hidden="true" />
            管理工具
          </h2>
          <div className="mt-1 text-sm text-muted">
            队列 {hasActiveTask ? "运行中" : "空闲"} · {queuedCount} 个排队 · 数据库 {healthyCount}/{databases.length} 可用
          </div>
        </div>
        <div className="inline-flex rounded-md border border-line bg-[#fbfcfe] p-1">
          <ManagementTab
            active={view === "queue"}
            icon={RefreshCcw}
            label="抓取队列"
            meta={hasActiveTask || queuedCount ? `${queuedCount} 排队` : "空闲"}
            onClick={() => onViewChange("queue")}
          />
          <ManagementTab active={view === "database"} icon={Database} label="数据库" meta={`${databases.length} 个`} onClick={() => onViewChange("database")} />
          <ManagementTab active={view === "auth"} icon={KeyRound} label={AUTH_TAB_LABEL} meta={authLabel} onClick={() => onViewChange("auth")} />
        </div>
      </div>
      {view === "queue" ? (
        <ProgressQueuePanel queue={queue} embedded />
      ) : view === "auth" ? (
        <div className="p-4">
          <AuthPanel cookieStatus={cookieStatus} onStatusChange={onCookieStatusChange || (() => undefined)} />
        </div>
      ) : (
        <DatabaseManagerPanel
          activeDatabaseName={activeDatabase?.name || activeDbId}
          activeDbId={activeDbId}
          databases={databases}
          healthyCount={healthyCount}
          hotplugDir={hotplugDir}
          importPath={importPath}
          isImporting={isImporting}
          isLoading={isLoading}
          legacyExportDir={legacyExportDir}
          onImportPathChange={onImportPathChange}
          onPickFiles={onPickFiles}
          onPickFolder={onPickFolder}
          onRefresh={onRefresh}
          onSelect={onSelect}
          onSubmitImport={onSubmitImport}
        />
      )}
    </section>
  );
}

function ManagementTab({ active, icon: Icon, label, meta, onClick }: { active: boolean; icon: LucideIcon; label: string; meta: string; onClick: () => void }) {
  return (
    <button
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition",
        active ? "bg-ink text-white" : "text-muted hover:bg-white hover:text-ink",
      )}
      type="button"
      onClick={onClick}
    >
      <Icon className={cn(label === "抓取队列" && active && "text-bilibili")} size={16} aria-hidden="true" />
      <span>{label}</span>
      <span className={cn("hidden text-xs sm:inline", active ? "text-white/75" : "text-muted")}>{meta}</span>
    </button>
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
  legacyExportDir: string;
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
  legacyExportDir,
  onImportPathChange,
  onPickFiles,
  onPickFolder,
  onRefresh,
  onSelect,
  onSubmitImport,
}: DatabaseManagerPanelProps) {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0 text-sm text-muted">
          {databases.length} 个已发现 · {healthyCount} 个可用 · 当前 {activeDatabaseName}
        </div>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-70"
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
            <InfoRow label="热插拔目录" value={hotplugDir} />
            <InfoRow label="兼容旧导出" value={legacyExportDir} />
          </div>
          <div className="mt-3 grid max-h-[290px] gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
            {databases.map((database) => (
              <DatabaseCard active={database.id === activeDbId} database={database} key={database.id} onSelect={() => onSelect(database.id)} />
            ))}
            {!isLoading && databases.length === 0 && <div className="rounded-md border border-dashed border-line bg-[#fbfcfe] p-4 text-sm text-muted">没有发现数据库</div>}
          </div>
        </div>

        <form className="grid content-start gap-3 rounded-md border border-line bg-[#fbfcfe] p-3" onSubmit={onSubmitImport}>
          <div>
            <div className="text-sm font-semibold text-ink">导入已有数据库</div>
            <div className="mt-1 text-xs text-muted">可导入 .db/.sqlite/.sqlite3 或导出的 JSON 数据文件。</div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-70"
              type="button"
              disabled={isImporting}
              onClick={onPickFiles}
            >
              <Upload size={16} aria-hidden="true" />
              选择文件
            </button>
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-70"
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
            <span className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line bg-white px-3 focus-within:border-bilibili focus-within:ring-2 focus-within:ring-pink-100">
              <FolderOpen size={16} aria-hidden="true" />
              <input className="min-w-0 flex-1 bg-transparent text-ink outline-none" placeholder="D:\\backups\\archive.db 或 archive.json" value={importPath} onChange={(event) => onImportPathChange(event.target.value)} />
            </span>
          </label>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
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
  const roleLabel = database.role === "main" ? "主库" : database.role === "legacy_export" ? "旧导出" : "热插拔";
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
        "grid min-w-0 gap-2 rounded-md border p-3 text-left transition",
        active ? "border-bilibili bg-pink-50" : "border-line bg-white hover:border-bilibili",
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
      {database.coverage_message && <div className={cn("line-clamp-2 text-xs", coverageTone)}>{database.coverage_message}</div>}
      <div className={cn("truncate text-xs", database.ok ? "text-muted" : "text-amber-700")}>{database.ok ? database.relative_path : database.error || "不可用"}</div>
    </button>
  );
}

function databaseKindLabel(kind: string) {
  if (kind === "main") return "主数据库";
  if (kind === "up") return "UP 主库";
  if (kind === "video") return "单视频库";
  if (kind === "collection") return "视频集合";
  return "未标注";
}
