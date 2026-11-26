import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchCommentData = vi.fn();
const refreshCommentData = vi.fn();
const stopRunningTask = vi.fn();
const fetchProgress = vi.fn();

vi.mock("../../../../frontend/src/api/client", () => ({
  fetchCommentData: (...args: unknown[]) => fetchCommentData(...args),
  refreshCommentData: (...args: unknown[]) => refreshCommentData(...args),
  stopRunningTask: (...args: unknown[]) => stopRunningTask(...args),
  fetchProgress: (...args: unknown[]) => fetchProgress(...args),
}));

import { VideoDetailPage } from "../../../../frontend/src/pages/VideoDetailPage";
import type { CommentData, CommentNode, ProgressState } from "../../../../frontend/src/types";
import { makeComment } from "../../helpers/factories";

function makeCommentData(items: CommentNode[], overrides: Partial<CommentData["metadata"]> = {}): CommentData {
  const bvid = overrides.bvid ?? "BV1xx411c7mD";
  const topLevel = items.filter((item) => item.normalized.level === 1);
  return {
    metadata: {
      source_url: `https://www.bilibili.com/video/${bvid}`,
      bvid,
      aid: 1,
      title: "Test video",
      fetched_at: "2024-01-01T00:00:00+08:00",
      sort: "ctime_ascending",
      api_comment_count: items.length,
      top_level_comment_count: topLevel.length,
      expected_nested_comment_count: 0,
      nested_comment_count: 0,
      comment_total_count: items.length,
      active_comment_count: items.length,
      deleted_comment_count: 0,
      limit: 500,
      offset: 0,
      has_more: false,
      child_fetch_summary: [],
      notes: [],
      ...overrides,
    },
    video_raw: {
      pic: "",
      owner: { name: "UP主" },
      stat: { view: 100, like: 5 },
    },
    comments: topLevel,
    comment_items: items,
  };
}

function idleProgress(): ProgressState {
  return {
    active: false,
    kind: "comments",
    bvid: "BV1xx411c7mD",
    message: "",
    logs: [],
    percent: 0,
    stage: "",
    stats: {},
    started_at: "",
    updated_at: "",
    done: false,
    queue: { active: null, queued: [], recent: [] },
  };
}

describe("VideoDetailPage filters and refresh", () => {
  beforeEach(() => {
    fetchCommentData.mockReset();
    refreshCommentData.mockReset();
    stopRunningTask.mockReset();
    fetchProgress.mockReset();
    fetchProgress.mockResolvedValue(idleProgress());
  });

  it("shows 没有匹配的评论 in the detail pane when every comment is filtered out", async () => {
    fetchCommentData.mockResolvedValue(
      makeCommentData([
        makeComment({ rpid: "1", message: "first comment" }),
        makeComment({ rpid: "2", message: "second comment" }),
      ]),
    );

    render(<VideoDetailPage bvid="BV1xx411c7mD" />);
    const search = await screen.findByLabelText("搜索评论、用户或 rpid");
    fireEvent.change(search, { target: { value: "no-such-comment" } });

    await waitFor(() => {
      expect(screen.getAllByText("没有匹配的评论")).toHaveLength(2);
    });

    const panes = screen.getAllByRole("complementary");
    const detailPane = panes[panes.length - 1];
    expect(within(detailPane).getByText("没有匹配的评论")).toBeTruthy();
    expect(within(detailPane).queryByText("first comment")).toBeNull();
  });

  it("does not replace the loaded list with a stopped refresh response", async () => {
    fetchCommentData.mockResolvedValue(
      makeCommentData([makeComment({ rpid: "1", message: "kept comment" })]),
    );
    let resolveRefresh: (payload: CommentData) => void = () => undefined;
    refreshCommentData.mockImplementation(
      () =>
        new Promise<CommentData>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    render(<VideoDetailPage bvid="BV1xx411c7mD" />);
    await screen.findByLabelText("搜索评论、用户或 rpid");
    fireEvent.click(screen.getByRole("button", { name: "刷新评论" }));
    await waitFor(() => expect(refreshCommentData).toHaveBeenCalledTimes(1));

    const stopped = makeCommentData([makeComment({ rpid: "9", message: "stopped page" })], {
      comment_total_count: 500,
    });
    stopped.refresh = {
      before_count: 1,
      after_count: 1,
      added_count: 0,
      stopped: true,
      reason: "已按请求停止抓取，本地档案未改动",
    };

    await act(async () => {
      resolveRefresh(stopped);
      await Promise.resolve();
    });

    expect(await screen.findByText("已按请求停止抓取，本地档案未改动")).toBeTruthy();
    expect(screen.getAllByText("kept comment").length).toBeGreaterThan(0);
    expect(screen.queryByText("stopped page")).toBeNull();
  });

  it("aborts the in-flight refresh when the page unmounts", async () => {
    fetchCommentData.mockResolvedValue(
      makeCommentData([makeComment({ rpid: "1", message: "kept comment" })]),
    );
    let observedSignal: AbortSignal | undefined;
    refreshCommentData.mockImplementation((...args: unknown[]) => {
      observedSignal = (args[2] as { signal?: AbortSignal } | undefined)?.signal;
      return new Promise(() => undefined);
    });

    const { unmount } = render(<VideoDetailPage bvid="BV1xx411c7mD" />);
    await screen.findByLabelText("搜索评论、用户或 rpid");
    fireEvent.click(screen.getByRole("button", { name: "刷新评论" }));
    await waitFor(() => expect(refreshCommentData).toHaveBeenCalledTimes(1));

    unmount();
    expect(observedSignal?.aborted).toBe(true);
  });
});
