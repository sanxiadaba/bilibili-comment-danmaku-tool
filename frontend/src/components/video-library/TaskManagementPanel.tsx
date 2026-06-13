import { Pause, Play, Square } from "lucide-react";
import type { ProgressQueue } from "../../types";
import { ProgressQueuePanel } from "./ProgressQueuePanel";

type TaskManagementPanelProps = {
  isControlling: boolean;
  queue?: ProgressQueue;
  onControl: (action: "pause" | "resume" | "stop", taskId?: string) => void;
};

export function TaskManagementPanel({ isControlling, queue, onControl }: TaskManagementPanelProps) {
  const active = queue?.active || null;
  const queued = queue?.queued || [];
  const hasWork = Boolean(active || queued.length);
  const hasPaused = queued.some((task) => task.status === "paused");

  return (
    <section className="mx-auto max-w-[1540px] px-4 pb-6 lg:px-6">
      <div className="rounded-md border border-line bg-white shadow-soft">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-ink">任务列表</h2>
            <p className="mt-1 text-sm text-muted">暂停会在当前视频处理完成后生效；停止会结束当前归档任务并保留已入库数据。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:border-bilibili hover:text-bilibili disabled:opacity-60" disabled={!hasWork || isControlling} type="button" onClick={() => onControl("pause")}>
              <Pause size={16} aria-hidden="true" />
              全部暂停
            </button>
            <button className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:border-bilibili hover:text-bilibili disabled:opacity-60" disabled={!hasPaused || isControlling} type="button" onClick={() => onControl("resume")}>
              <Play size={16} aria-hidden="true" />
              继续
            </button>
            <button className="inline-flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-medium text-white hover:bg-[#26344f] disabled:opacity-60" disabled={!hasWork || isControlling} type="button" onClick={() => onControl("stop")}>
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
