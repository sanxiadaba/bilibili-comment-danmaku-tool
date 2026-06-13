import { Pause, Play, Square } from "lucide-react";
import type { TaskControlAction } from "../../api/client";
import type { ProgressQueue } from "../../types";
import { ProgressQueuePanel } from "./ProgressQueuePanel";

type TaskManagementPanelProps = {
  isControlling: boolean;
  queue?: ProgressQueue;
  onControl: (action: TaskControlAction, taskId?: string) => void;
};

export function TaskManagementPanel({ isControlling, queue, onControl }: TaskManagementPanelProps) {
  const active = queue?.active || null;
  const queued = queue?.queued || [];
  const controllableTasks = [active, ...queued].filter(
    (task) => task && isControllableTaskKind(task.kind) && !isTerminalTaskStatus(task.status),
  );
  const hasPauseableWork = controllableTasks.some(
    (task) => task && !task.pause_requested && !task.stop_requested && task.status !== "paused",
  );
  const hasResumableWork = controllableTasks.some((task) => task && (task.status === "paused" || task.pause_requested));
  const hasStoppableWork = controllableTasks.some((task) => task && !task.stop_requested);

  return (
    <section className="mx-auto max-w-[1540px] px-4 pb-6 lg:px-6">
      <div className="surface-card rounded-md">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/80 bg-white/42 px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-ink">任务列表</h2>
            <p className="mt-1 text-sm text-muted">暂停会在当前阶段完成后生效；停止会结束当前任务并保留已入库数据。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-quiet inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60" disabled={!hasPauseableWork || isControlling} type="button" onClick={() => onControl("pause")}>
              <Pause size={16} aria-hidden="true" />
              全部暂停
            </button>
            <button className="btn-quiet inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60" disabled={!hasResumableWork || isControlling} type="button" onClick={() => onControl("resume")}>
              <Play size={16} aria-hidden="true" />
              继续
            </button>
            <button className="btn-primary inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60" disabled={!hasStoppableWork || isControlling} type="button" onClick={() => onControl("stop")}>
              <Square size={16} aria-hidden="true" />
              全部停止
            </button>
          </div>
        </div>
        <ProgressQueuePanel embedded isControlling={isControlling} queue={queue} onControl={onControl} />
      </div>
    </section>
  );
}

function isControllableTaskKind(kind: string) {
  return kind === "space" || kind === "space_archive" || kind === "parse" || kind === "delete";
}

function isTerminalTaskStatus(status: string) {
  return status === "finished" || status === "failed" || status === "stopped";
}
