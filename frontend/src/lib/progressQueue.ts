import type { ProgressQueue, ProgressState, ProgressTask } from "../types";

const SINGLE_VIDEO_TASK_KINDS = new Set(["parse", "comments", "danmaku"]);

export function mergeProgressIntoQueue(
  queue: ProgressQueue | undefined,
  progress: ProgressState | null,
  hiddenTaskKeys: Set<string> = new Set(),
): ProgressQueue {
  const base: ProgressQueue = {
    active: queue?.active || null,
    queued: queue?.queued || [],
    recent: (queue?.recent || []).filter((task) => !isHiddenTask(task, hiddenTaskKeys)),
  };
  const progressTask = progressToTask(progress);
  if (!progressTask || isHiddenTask(progressTask, hiddenTaskKeys) || queueHasMatchingTask(base, progressTask)) {
    return base;
  }

  if (progressTask.status === "running" || progressTask.status === "waiting") {
    return {
      ...base,
      active: progressTask,
    };
  }

  const alreadyInRecent = base.recent.some((task) => task.id === progressTask.id);
  return {
    ...base,
    recent: alreadyInRecent ? base.recent : [progressTask, ...base.recent],
  };
}

function isHiddenTask(task: ProgressTask, hiddenTaskKeys: Set<string>) {
  return taskHideKeys(task).some((key) => hiddenTaskKeys.has(key));
}

export function taskHideKeys(task: Pick<ProgressTask, "id" | "kind"> & Partial<Pick<ProgressTask, "bvid" | "current_bvid">>) {
  const keys = [`id:${task.id}`];
  const bvid = task.bvid || task.current_bvid;
  if (bvid && SINGLE_VIDEO_TASK_KINDS.has(task.kind)) {
    keys.push(`id:${task.kind}:${bvid}`);
  }
  return keys;
}

function queueHasMatchingTask(queue: ProgressQueue, task: ProgressTask) {
  return [queue.active, ...queue.queued, ...queue.recent].some((existing) => {
    if (!existing) return false;
    if (existing.id === task.id) return true;
    const existingBvid = existing.bvid || existing.current_bvid;
    const taskBvid = task.bvid || task.current_bvid;
    return Boolean(existingBvid && taskBvid && existing.kind === task.kind && existingBvid === taskBvid);
  });
}

function progressToTask(progress: ProgressState | null): ProgressTask | null {
  if (!progress || !SINGLE_VIDEO_TASK_KINDS.has(progress.kind)) return null;
  const bvid = progress.bvid || "";
  const taskKindLabel = progress.kind === "parse" ? "视频抓取" : progress.kind === "comments" ? "评论刷新" : "弹幕刷新";
  const status = progress.active ? "running" : progress.error ? "failed" : progress.done ? "finished" : "queued";
  return {
    id: `${progress.kind}:${bvid || progress.started_at || "latest"}`,
    kind: progress.kind,
    mid: "",
    owner_ref: taskKindLabel,
    status,
    message: progress.message || taskKindLabel,
    created_at: progress.started_at,
    updated_at: progress.updated_at,
    started_at: progress.started_at,
    finished_at: progress.done ? progress.updated_at : "",
    progress: progress.percent || 0,
    current_bvid: bvid,
    total: 1,
    complete: progress.done && !progress.error ? 1 : 0,
    archived: progress.done && !progress.error ? 1 : 0,
    skipped: 0,
    failed: progress.error ? 1 : 0,
  };
}
