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
      try {
        const payload = await fetchProgress();
        if (stopped) return;
        if (!kind || payload.kind === kind || payload.active) {
          setProgress(payload);
        }
      } catch {
        // Progress is best-effort; the main request still owns the final result.
      }
      if (!stopped) {
        timer = window.setTimeout(tick, 900);
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
