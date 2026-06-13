import { Database, KeyRound, ListVideo, RefreshCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/utils";
import type { LibraryView } from "./types";

type LibraryTabsProps = {
  active: LibraryView;
  databaseCount: number;
  hasTaskWork: boolean;
  queuedCount: number;
  videoCount: number;
  onChange: (view: LibraryView) => void;
};

export function LibraryTabs({ active, databaseCount, hasTaskWork, queuedCount, videoCount, onChange }: LibraryTabsProps) {
  return (
    <nav className="mx-auto flex max-w-[1540px] gap-2 px-4 py-3 lg:px-6" aria-label="主视图">
      <TabButton active={active === "videos"} icon={ListVideo} label="视频列表" meta={`${videoCount} 个`} onClick={() => onChange("videos")} />
      <TabButton
        active={active === "tasks"}
        icon={RefreshCcw}
        label="任务列表"
        meta={hasTaskWork ? `${queuedCount} 排队` : "空闲"}
        onClick={() => onChange("tasks")}
      />
      <TabButton active={active === "databases"} icon={Database} label="数据库" meta={`${databaseCount} 个`} onClick={() => onChange("databases")} />
      <TabButton active={active === "auth"} icon={KeyRound} label="登录态" meta="扫码 / Cookie" onClick={() => onChange("auth")} />
    </nav>
  );
}

function TabButton({
  active,
  icon: Icon,
  label,
  meta,
  onClick,
}: {
  active: boolean;
  icon: LucideIcon;
  label: string;
  meta: string;
  onClick: () => void;
}) {
  return (
    <button
      className={cn(
        "inline-flex h-10 items-center gap-2 rounded-md border px-3 text-sm font-medium transition",
        active ? "border-ink bg-ink text-white" : "border-line bg-white text-ink hover:border-bilibili hover:text-bilibili",
      )}
      type="button"
      onClick={onClick}
    >
      <Icon size={16} aria-hidden="true" />
      <span>{label}</span>
      <span className={cn("rounded px-1.5 py-0.5 text-xs", active ? "bg-white/15 text-white/80" : "bg-[#f4f7fb] text-muted")}>{meta}</span>
    </button>
  );
}
