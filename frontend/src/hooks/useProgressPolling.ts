import { useEffect, useState } from "react";
import { fetchProgress } from "../api/client";
import type { ProgressState } from "../types";

export function useProgressPolling(enabled: boolean, kind?: string) {
  const [progress, setProgress] = useState<ProgressState | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: number | undefined;

    const tick = async () => {
      let nextDelay: number;
      try {
        const payload = await fetchProgress();
        if (stopped) return;
        if (!kind || payload.kind === kind || payload.active) {
          setProgress(payload);
        }
        nextDelay = progressPollingDelay(payload);
      } catch {
        // Progress is best-effort; the main request still owns the final result.
        nextDelay = 15_000;
      }
      if (!stopped) {
        timer = window.setTimeout(tick, progressPollingDelay(undefined, document.hidden, nextDelay));
      }
    };

    void tick();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [enabled, kind]);

  return progress;
}

export function progressPollingDelay(payload?: ProgressState, hidden = false, fallback = 10_000) {
  const queueBusy = Boolean(payload?.active || payload?.queue?.active || payload?.queue?.queued?.length);
  const delay = payload ? (queueBusy ? 900 : 10_000) : fallback;
  return hidden ? Math.max(delay, 30_000) : delay;
}
