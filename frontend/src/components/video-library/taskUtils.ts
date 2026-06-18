import type { ProgressTask, TaskControlAction } from "../../types";

export function isControllableTaskKind(kind: string) {
  return kind === "space" || kind === "space_archive" || kind === "parse" || kind === "delete";
}

export function isTerminalTaskStatus(status: string) {
  return status === "finished" || status === "failed" || status === "stopped";
}

export function taskTitle(task: ProgressTask) {
  const bvid = task.bvid || task.current_bvid;
  if (task.kind === "delete") return task.owner_ref || (bvid ? `删除 ${bvid}` : "删除本地档案");
  if (task.kind === "parse") return bvid ? `视频 ${bvid}` : "视频抓取";
  if (task.mid) return `UP ${task.mid}`;
  return task.owner_ref || task.id;
}

export function taskStatusLabel(task: ProgressTask) {
  if (task.status === "running") return "运行中";
  if (task.status === "waiting") return "等待当前任务";
  if (task.status === "queued") return "排队中";
  if (task.status === "paused") return "已暂停";
  if (task.status === "stopped") return "已停止";
  if (task.status === "finished") return "已完成";
  if (task.status === "failed") return "失败";
  return task.status || "未知";
}

export function taskActionLabel(action: TaskControlAction) {
  if (action === "pause") return "暂停";
  if (action === "resume") return "继续";
  if (action === "stop") return "停止";
  if (action === "retry") return "重试";
  return "清除";
}
