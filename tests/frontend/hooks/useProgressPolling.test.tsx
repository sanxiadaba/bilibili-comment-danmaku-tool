import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

const fetchProgress = vi.fn();

vi.mock("../../../frontend/src/api/client", () => ({
  fetchProgress: (...args: unknown[]) => fetchProgress(...args),
}));

import { useProgressPolling } from "../../../frontend/src/hooks/useProgressPolling";
import type { ProgressState } from "../../../frontend/src/types";

function Probe({ kind }: { kind?: string }) {
  const progress = useProgressPolling(true, kind);
  return <div data-testid="kind">{progress?.kind ?? "none"}</div>;
}

function payload(kind: string, active: boolean): ProgressState {
  return {
    kind,
    active,
    bvid: "BV1xx411c7mD",
    message: "working",
    logs: [],
    percent: 10,
    stage: "",
    stats: {},
    started_at: "",
    updated_at: "",
    done: false,
    error: "",
    queue: { active: null, queued: [], recent: [] },
  } as unknown as ProgressState;
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useProgressPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchProgress.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ignores progress that belongs to another task kind", async () => {
    fetchProgress.mockResolvedValue(payload("space", true));

    render(<Probe kind="comments" />);
    await settle();

    expect(fetchProgress).toHaveBeenCalled();
    expect(screen.getByTestId("kind").textContent).toBe("none");
  });

  it("accepts progress for the watched kind", async () => {
    fetchProgress.mockResolvedValue(payload("comments", true));

    render(<Probe kind="comments" />);
    await settle();

    expect(screen.getByTestId("kind").textContent).toBe("comments");
  });

  it("polls fast while a task runs and slowly when idle", async () => {
    fetchProgress.mockResolvedValue(payload("comments", true));
    render(<Probe kind="comments" />);
    await settle();
    expect(fetchProgress).toHaveBeenCalledTimes(1);

    await advance(900);
    expect(fetchProgress.mock.calls.length).toBeGreaterThanOrEqual(2);

    fetchProgress.mockResolvedValue(payload("comments", false));
    await advance(900);
    const callsWhileIdle = fetchProgress.mock.calls.length;

    // Idle polling waits 4s, so 900ms more must not add a request.
    await advance(900);
    expect(fetchProgress.mock.calls.length).toBe(callsWhileIdle);

    await advance(3200);
    expect(fetchProgress.mock.calls.length).toBeGreaterThan(callsWhileIdle);
  });

  it("aborts the in-flight request on unmount", async () => {
    let observedSignal: AbortSignal | undefined;
    fetchProgress.mockImplementation((signal?: AbortSignal) => {
      observedSignal = signal;
      return new Promise(() => {});
    });

    const { unmount } = render(<Probe kind="comments" />);
    await settle();
    expect(fetchProgress).toHaveBeenCalled();

    unmount();

    expect(observedSignal?.aborted).toBe(true);
  });
});
