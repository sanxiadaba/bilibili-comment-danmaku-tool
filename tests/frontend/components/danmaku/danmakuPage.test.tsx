import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchDanmakuData = vi.fn();
const refreshDanmakuData = vi.fn();
const stopRunningTask = vi.fn();
const fetchProgress = vi.fn();

vi.mock("../../../../frontend/src/api/client", () => ({
  fetchDanmakuData: (...args: unknown[]) => fetchDanmakuData(...args),
  refreshDanmakuData: (...args: unknown[]) => refreshDanmakuData(...args),
  stopRunningTask: (...args: unknown[]) => stopRunningTask(...args),
  fetchProgress: (...args: unknown[]) => fetchProgress(...args),
}));

import { DanmakuPage } from "../../../../frontend/src/pages/DanmakuPage";
import type { DanmakuData, DanmakuItem } from "../../../../frontend/src/types";
import { makeDanmaku } from "../../helpers/factories";

function makeDanmakuData(items: DanmakuItem[], overrides: Partial<DanmakuData["metadata"]> = {}): DanmakuData {
  return {
    metadata: {
      bvid: "BV1xx411c7mD",
      cid: "456",
      title: "Test video",
      duration: 300,
      total_count: items.length,
      fetched_at: "2024-01-01T00:00:00+00:00",
      max_progress: 300,
      limit: 2000,
      offset: 0,
      has_more: false,
      ...overrides,
    },
    items,
    buckets: [],
  };
}

describe("DanmakuPage progress range", () => {
  beforeEach(() => {
    fetchDanmakuData.mockReset();
    refreshDanmakuData.mockReset();
    stopRunningTask.mockReset();
    fetchProgress.mockReset();
    fetchProgress.mockResolvedValue({ active: false, kind: "danmaku" });
  });

  it("falls back to the largest item progress when max_progress is 0", async () => {
    fetchDanmakuData.mockResolvedValue(
      makeDanmakuData([makeDanmaku({ dmid: "1", progress: 125, content: "late danmaku" })], {
        max_progress: 0,
      }),
    );

    render(<DanmakuPage bvid="BV1xx411c7mD" />);
    await screen.findByLabelText("搜索弹幕、dmid 或颜色");

    expect(screen.getByText(/00:00 - 02:05/)).toBeTruthy();
    const slider = screen.getByRole("slider") as HTMLInputElement;
    expect(slider.disabled).toBe(false);
    expect(screen.queryByText("弹幕没有进度数据，进度筛选不可用")).toBeNull();
  });

  it("disables the slider and explains why when no progress data exists", async () => {
    fetchDanmakuData.mockResolvedValue(
      makeDanmakuData([makeDanmaku({ dmid: "1", progress: 0, content: "no progress" })], {
        max_progress: 0,
      }),
    );

    render(<DanmakuPage bvid="BV1xx411c7mD" />);
    await screen.findByLabelText("搜索弹幕、dmid 或颜色");

    const slider = screen.getByRole("slider") as HTMLInputElement;
    expect(slider.disabled).toBe(true);
    expect(screen.getByText("弹幕没有进度数据，进度筛选不可用")).toBeTruthy();
  });

  it("warns when the loaded rows are truncated below the archive total", async () => {
    fetchDanmakuData.mockResolvedValue(
      makeDanmakuData([makeDanmaku({ dmid: "1", progress: 1 }), makeDanmaku({ dmid: "2", progress: 2 })], {
        total_count: 5,
        max_progress: 300,
      }),
    );

    render(<DanmakuPage bvid="BV1xx411c7mD" />);
    await screen.findByLabelText("搜索弹幕、dmid 或颜色");

    expect(screen.getByText(/仅载入 2\/5，已截断/)).toBeTruthy();
  });
});
