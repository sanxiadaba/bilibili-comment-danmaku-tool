import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ExportChoiceDialog } from "../../../../frontend/src/components/video-library/ExportChoiceDialog";
import { ManagementPanel } from "../../../../frontend/src/components/video-library/ManagementPanel";
import { OwnerFilterButton } from "../../../../frontend/src/components/video-library/OwnerFilterButton";
import { ProgressQueuePanel } from "../../../../frontend/src/components/video-library/ProgressQueuePanel";
import { TaskManagementPanel } from "../../../../frontend/src/components/video-library/TaskManagementPanel";
import type { OwnerGroup } from "../../../../frontend/src/components/video-library/types";
import { makeDatabase, makeProgressTask, makeVideo } from "../../helpers/factories";

describe("video library management components", () => {
  it("renders queue progress across active, queued and recent tasks", () => {
    const html = renderToStaticMarkup(
      <ProgressQueuePanel
        queue={{
          active: makeProgressTask({ progress: 55, message: "active task" }),
          queued: [makeProgressTask({ id: "task-2", status: "queued", queue_position: 1, message: "queued task" })],
          recent: [makeProgressTask({ id: "task-3", status: "finished", progress: 100, message: "done task" })],
        }}
      />,
    );

    expect(html).toContain("55%");
    expect(html).toContain("active task");
    expect(html).toContain("queued task");
    expect(html).toContain("done task");
    expect(html).toContain("抓取队列");
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
    expect(html).toContain("等待暂停");
    expect(html).toContain("paused task");
  });

  it("shows single-video progress tasks without archive controls", () => {
    const html = renderToStaticMarkup(
      <TaskManagementPanel
        isControlling={false}
        queue={{
          active: makeProgressTask({
            id: "parse:BV1xx411c7mD",
            kind: "parse",
            mid: "",
            owner_ref: "视频抓取",
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

    expect(html).toContain("视频抓取");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).not.toContain("等待暂停");
    expect(html).not.toContain("等待停止");
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
