import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ExportChoiceDialog } from "../../../../frontend/src/components/video-library/ExportChoiceDialog";
import { ManagementPanel } from "../../../../frontend/src/components/video-library/ManagementPanel";
import { OwnerFilterButton } from "../../../../frontend/src/components/video-library/OwnerFilterButton";
import { ProgressQueuePanel } from "../../../../frontend/src/components/video-library/ProgressQueuePanel";
import { TaskManagementPanel } from "../../../../frontend/src/components/video-library/TaskManagementPanel";
import { mergeProgressIntoQueue } from "../../../../frontend/src/pages/VideoLibraryPage";
import type { OwnerGroup } from "../../../../frontend/src/components/video-library/types";
import { makeDatabase, makeProgress, makeProgressTask, makeVideo } from "../../helpers/factories";

describe("video library management components", () => {
  it("renders queue progress across active, queued and recent tasks", () => {
    const html = renderToStaticMarkup(
      <ProgressQueuePanel
        onControl={() => undefined}
        queue={{
          active: makeProgressTask({ progress: 55, message: "active task" }),
          queued: [makeProgressTask({ id: "task-2", status: "queued", queue_position: 1, message: "queued task" })],
          recent: [makeProgressTask({ id: "task-3", status: "failed", progress: 100, message: "done task" })],
        }}
      />,
    );

    expect(html).toContain("55%");
    expect(html).toContain("active task");
    expect(html).toContain("queued task");
    expect(html).toContain("done task");
    expect(html).toContain("抓取队列");
    expect(html).toContain("重试");
    expect(html).toContain("清除");
    expect(html).toContain("清空记录");
  });

  it("renders task controls for active and paused queue work", () => {
    const html = renderToStaticMarkup(
      <TaskManagementPanel
        isControlling={false}
        queue={{
          active: makeProgressTask({ id: "task-1", status: "running", pause_requested: true }),
          queued: [makeProgressTask({ id: "task-2", status: "paused", message: "paused task" })],
          recent: [],
        }}
        onControl={() => undefined}
      />,
    );

    expect(html).toContain("全部暂停");
    expect(html).toContain("继续");
    expect(html).toContain("取消暂停");
    expect(html).toContain("paused task");
  });

  it("disables global controls when only history tasks remain", () => {
    const html = renderToStaticMarkup(
      <TaskManagementPanel
        isControlling={false}
        queue={{
          active: null,
          queued: [],
          recent: [makeProgressTask({ id: "task-1", status: "failed", message: "failed task" })],
        }}
        onControl={() => undefined}
      />,
    );

    expect(html).toContain("全部暂停");
    expect(html).toContain("disabled");
    expect(html).toContain("failed task");
    expect(html).toContain("重试");
  });

  it("shows single-video progress tasks with task controls", () => {
    const html = renderToStaticMarkup(
      <TaskManagementPanel
        isControlling={false}
        queue={{
          active: makeProgressTask({
            id: "parse:BV1xx411c7mD",
            kind: "parse",
            mid: "",
            owner_ref: "视频抓取",
            bvid: "BV1xx411c7mD",
            status: "running",
            message: "正在抓取评论",
            current_bvid: "BV1xx411c7mD",
          }),
          queued: [],
          recent: [],
        }}
        onControl={() => undefined}
      />,
    );

    expect(html).toContain("视频 BV1xx411c7mD");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).toContain("暂停");
    expect(html).toContain("停止");
  });

  it("does not duplicate completed parse progress when queue already has the task", () => {
    const queue = {
      active: null,
      queued: [],
      recent: [
        makeProgressTask({
          id: "parse-1",
          kind: "parse",
          bvid: "BV1JogwzEEzD",
          current_bvid: "BV1JogwzEEzD",
          status: "finished",
        }),
      ],
    };

    const merged = mergeProgressIntoQueue(
      queue,
      makeProgress({
        active: false,
        done: true,
        kind: "parse",
        bvid: "BV1JogwzEEzD",
        percent: 100,
        message: "解析与抓取完成",
      }),
    );

    expect(merged.recent).toHaveLength(1);
    expect(merged.recent[0].id).toBe("parse-1");
  });

  it("does not re-add hidden progress tasks after clearing history", () => {
    const merged = mergeProgressIntoQueue(
      { active: null, queued: [], recent: [] },
      makeProgress({
        active: false,
        done: true,
        kind: "parse",
        bvid: "BV1JogwzEEzD",
        percent: 100,
        message: "解析与抓取完成",
      }),
      new Set(["id:parse:BV1JogwzEEzD"]),
    );

    expect(merged.recent).toHaveLength(0);
  });

  it("renders database management cards and import controls", () => {
    const html = renderToStaticMarkup(
      <ManagementPanel
        activeDbId="main"
        databases={[makeDatabase(), makeDatabase({ id: "archive", name: "Archive", role: "hotplug" })]}
        hotplugDir="D:/data/hotplug"
        importPath="D:/backup/archive.json"
        isImporting={false}
        isLoading={false}
        legacyExportDir="D:/data/exports"
        queue={{ active: null, queued: [], recent: [] }}
        view="database"
        onImportPathChange={() => undefined}
        onPickFiles={() => undefined}
        onPickFolder={() => undefined}
        onRefresh={() => undefined}
        onSelect={() => undefined}
        onSubmitImport={(event) => event.preventDefault()}
        onViewChange={() => undefined}
      />,
    );

    expect(html).toContain("Main archive");
    expect(html).toContain("Archive");
    expect(html).toContain("D:/data/hotplug");
    expect(html).toContain("D:/backup/archive.json");
  });

  it("renders owner export affordance and export format choices", () => {
    const onClick = vi.fn();
    const owner: OwnerGroup = {
      bvids: ["BV1xx411c7mD"],
      key: "mid:42",
      name: "Owner",
      ownerMid: "42",
      videoCount: 2,
      commentCount: 20,
      danmakuCount: 8,
    };

    const ownerHtml = renderToStaticMarkup(
      <OwnerFilterButton
        active
        commentCount={owner.commentCount}
        danmakuCount={owner.danmakuCount}
        name={owner.name}
        videoCount={owner.videoCount}
        onClick={onClick}
        onExport={() => undefined}
      />,
    );
    expect(ownerHtml).toContain("Owner");
    expect(ownerHtml).toContain("20");
    expect(ownerHtml).toContain("8");

    const dialogHtml = renderToStaticMarkup(
      <ExportChoiceDialog target={{ kind: "video", video: makeVideo({ title: "Video A" }) }} onChoose={() => undefined} onClose={() => undefined} />,
    );
    expect(dialogHtml).toContain("Video A");
    expect(dialogHtml).toContain("SQLite");
    expect(dialogHtml).toContain("JSON");
  });
});
