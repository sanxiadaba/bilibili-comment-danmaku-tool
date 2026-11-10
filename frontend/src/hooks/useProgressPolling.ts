import { useEffect, useState } from "react";
import { fetchProgress } from "../api/client";
import type { ProgressState } from "../types";

const ACTIVE_POLL_MS = 900;
const IDLE_POLL_MS = 4000;

function hasRunningWork(progress: ProgressState | null) {
  if (!progress) return false;
  if (progress.active) return true;
  return Array.isArray(progress.queue?.queued) && progress.queue.queued.length > 0;
}

function tabHidden() {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export function useProgressPolling(enabled: boolean, kind?: string) {
  const [progress, setProgress] = useState<ProgressState | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;

    const schedule = (delay: number) => {
      if (!stopped) timer = window.setTimeout(tick, delay);
    };

    const tick = async () => {
      // A background tab does not need a progress bar; resume as soon as it is visible again.
      if (tabHidden()) {
        schedule(IDLE_POLL_MS);
        return;
      }
      try {
        controller = new AbortController();
        const payload = await fetchProgress(controller.signal);
        if (stopped) return;
        // Only accept progress that belongs to the task this hook is watching: an unrelated
        // queued task must not take over this page's banner.
        if (!kind || payload.kind === kind) {
          setProgress(payload);
        }
        schedule(hasRunningWork(payload) ? ACTIVE_POLL_MS : IDLE_POLL_MS);
      } catch {
        // Progress is best-effort; the main request still owns the final result.
        schedule(IDLE_POLL_MS);
      }
    };

    void tick();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [enabled, kind]);

  return progress;
}
