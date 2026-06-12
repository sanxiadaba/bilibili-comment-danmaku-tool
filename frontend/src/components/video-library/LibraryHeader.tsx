import { Database, RefreshCcw, Settings } from "lucide-react";
import { cn, formatNumber } from "../../lib/utils";
import type { DatabaseInfo } from "../../types";

type LibraryHeaderProps = {
  activeDatabase?: DatabaseInfo;
  commentCount: number;
  isLoading: boolean;
  isLoadingDatabases: boolean;
  showSettings: boolean;
  videoCount: number;
  onRefresh: () => void;
  onToggleSettings: () => void;
};

export function LibraryHeader({
  activeDatabase,
  commentCount,
  isLoading,
  isLoadingDatabases,
  showSettings,
  videoCount,
  onRefresh,
  onToggleSettings,
}: LibraryHeaderProps) {
  const busy = isLoading || isLoadingDatabases;
  return (
    <section className="border-b border-line bg-white">
      <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-6">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="inline-flex items-center gap-1">
              <Database size={15} aria-hidden="true" />
              评论视频库
            </span>
            <span>{videoCount} 个视频</span>
            <span>{formatNumber(commentCount)} 条评论档案</span>
            {activeDatabase && <span>当前库：{activeDatabase.name}</span>}
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-normal text-ink lg:text-3xl">
            Bilibili 评论弹幕管理
          </h1>
        </div>
        <div className="flex items-center gap-2 self-center">
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
            type="button"
            onClick={onRefresh}
            disabled={busy}
          >
            <RefreshCcw className={cn(busy && "animate-spin")} size={16} aria-hidden="true" />
            刷新列表
          </button>
          <button
            className={cn(
              "inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium transition",
              showSettings ? "border-bilibili text-bilibili" : "text-muted hover:border-ink hover:text-ink",
            )}
            type="button"
            onClick={onToggleSettings}
          >
            <Settings size={16} aria-hidden="true" />
            设置
          </button>
        </div>
      </div>
    </section>
  );
}
