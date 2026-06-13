import { Pause, Play, RefreshCcw, Square } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/utils";
import type { ProgressQueue, ProgressTask } from "../../types";

type ProgressQueuePanelProps = {
  embedded?: boolean;
  isControlling?: boolean;
  queue?: ProgressQueue;
  onControl?: (action: "pause" | "resume" | "stop", taskId?: string) => void;
};

export function ProgressQueuePanel({ embedded = false, isControlling = false, queue, onControl }: ProgressQueuePanelProps) {
  const queued = queue?.queued || [];
  const recent = queue?.recent || [];
  const active = queue?.active || null;
  const content = (
    <>
      {!embedded && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <RefreshCcw className={cn(active && "animate-spin text-bilibili")} size={18} aria-hidden="true" />
            抓取队列
          </h2>
          <span className="text-sm text-muted">
            {active ? "1 个运行中" : "无运行任务"} / {queued.length} 个排队中
          </span>
        </div>
      )}
      <div className="grid gap-3 p-4">
        {active ? (
          <QueueTaskRow isControlling={isControlling} onControl={onControl} task={active} tone="active" />
        ) : (
          <div className="rounded-md border border-dashed border-line bg-[#fbfcfe] px-3 py-3 text-sm text-muted">
            暂无正在运行的抓取任务
          </div>
        )}
        {queued.length > 0 && (
          <div className="grid gap-2">
            {queued.map((task) => (
              <QueueTaskRow isControlling={isControlling} key={task.id} onControl={onControl} task={task} tone="queued" />
            ))}
          </div>
        )}
        {queued.length === 0 && !active && recent.length === 0 && <div className="text-sm text-muted">暂无排队任务</div>}
        {recent.length > 0 && (
          <div className="grid gap-2 border-t border-line pt-3">
            <div className="text-xs font-medium uppercase tracking-normal text-muted">最近完成</div>
            {recent.slice(0, 3).map((task) => (
              <QueueTaskRow key={task.id} task={task} tone="recent" />
            ))}
          </div>
        )}
      </div>
    </>
  );

  if (embedded) {
    return <div>{content}</div>;
  }

  return <section className="rounded-md border border-line bg-white shadow-soft">{content}</section>;
}

function QueueTaskRow({
  isControlling = false,
  onControl,
  task,
  tone,
}: {
  isControlling?: boolean;
  onControl?: (action: "pause" | "resume" | "stop", taskId?: string) => void;
  task: ProgressTask;
  tone: "active" | "queued" | "recent";
}) {
  const percent = Math.max(0, Math.min(100, Math.round(task.progress || 0)));
  const status = taskStatusLabel(task);
  const title = taskTitle(task);
  const canControl = Boolean(onControl) && tone !== "recent" && isControllableTaskKind(task.kind);
  const isPaused = task.status === "paused";
  return (
    <div
      className={cn(
        "min-w-0 rounded-md border px-3 py-3",
        tone === "active" ? "border-bilibili/30 bg-pink-50" : tone === "queued" ? "border-line bg-[#fbfcfe]" : "border-line bg-white",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-ink">{title}</span>
            <span className="rounded bg-white px-2 py-0.5 text-xs text-muted">{status}</span>
            {task.queue_position && <span className="text-xs text-muted">排队第 {task.queue_position}</span>}
          </div>
          <div className="mt-1 truncate text-xs text-muted">
            {task.message || "等待抓取"}
            {task.current_bvid ? ` / ${task.current_bvid}` : ""}
          </div>
        </div>
        <div className="shrink-0 text-right text-xs text-muted">
          <div className="font-medium text-ink">{percent}%</div>
          <div>
            {task.complete || 0}/{task.total || 0}
          </div>
          <div>
            新增 {task.archived || 0} / 跳过 {task.skipped || 0} / 失败 {task.failed || 0}
          </div>
        </div>
      </div>
      {canControl && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {isPaused ? (
            <TaskButton disabled={isControlling} icon={Play} label="继续" onClick={() => onControl?.("resume", task.id)} />
          ) : (
            <TaskButton disabled={isControlling || task.pause_requested} icon={Pause} label={task.pause_requested ? "等待暂停" : "暂停"} onClick={() => onControl?.("pause", task.id)} />
          )}
          <TaskButton disabled={isControlling || task.stop_requested} icon={Square} label={task.stop_requested ? "等待停止" : "停止"} onClick={() => onControl?.("stop", task.id)} />
        </div>
      )}
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white">
        <div className="h-full rounded-full bg-bilibili transition-all duration-300" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function TaskButton({
  disabled,
  icon: Icon,
  label,
  onClick,
}: {
  disabled?: boolean;
  icon: LucideIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-line bg-white px-2.5 text-xs font-medium text-ink transition hover:border-bilibili hover:text-bilibili disabled:cursor-wait disabled:opacity-60"
      disabled={disabled}
      type="button"
      onClick={onClick}
    >
      <Icon size={14} aria-hidden="true" />
      {label}
    </button>
  );
}

function taskTitle(task: ProgressTask) {
  const bvid = task.bvid || task.current_bvid;
  if (task.kind === "parse") return bvid ? `视频 ${bvid}` : "视频抓取";
  if (task.mid) return `UP ${task.mid}`;
  return task.owner_ref || task.id;
}

function taskStatusLabel(task: ProgressTask) {
  if (task.status === "running") return "运行中";
  if (task.status === "waiting") return "等待当前任务";
  if (task.status === "queued") return "排队中";
  if (task.status === "paused") return "已暂停";
  if (task.status === "stopped") return "已停止";
  if (task.status === "finished") return "已完成";
  if (task.status === "failed") return "失败";
  return task.status || "未知";
}

function isControllableTaskKind(kind: string) {
  return kind === "space" || kind === "space_archive" || kind === "parse";
}
