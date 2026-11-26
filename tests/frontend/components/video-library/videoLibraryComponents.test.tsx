import { render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LibraryHeader } from "../../../../frontend/src/components/video-library/LibraryHeader";
import { LibraryStats } from "../../../../frontend/src/components/video-library/LibraryStats";
import { LibrarySidebar } from "../../../../frontend/src/components/video-library/LibrarySidebar";
import { StatusStrips } from "../../../../frontend/src/components/video-library/StatusStrips";
import { NoticeDialog } from "../../../../frontend/src/components/video-library/NoticeDialog";
import { VideoListPanel } from "../../../../frontend/src/components/video-library/VideoListPanel";
import { makeCookieStatus, makeProgress, makeVideo } from "../../helpers/factories";

// jsdom has no layout: give the virtualized list a measurable viewport.
Object.defineProperty(HTMLElement.prototype, "clientHeight", {
  configurable: true,
  get() {
    return 480;
  },
});

describe("video library components", () => {
  it("renders library totals without mutating values", () => {
    const html = renderToStaticMarkup(
      <LibraryStats
        videoCount={2}
        totals={{ views: 1000, comments: 50, active: 40, deleted: 10, likes: 99, danmaku: 8 }}
      />,
    );

    expect(html).toContain("2");
    expect(html).toContain("1,000");
    expect(html).toContain("40 / 10");
    expect(html).toContain("99");
  });

  it("shows error before message and renders progress banners", () => {
    const errorHtml = renderToStaticMarkup(
      <StatusStrips
        error="failed"
        message="success"
        isParsing={false}
        hasSpaceQueueWork={false}
        parseProgress={null}
        spaceProgress={null}
      />,
    );
    expect(errorHtml).toContain("failed");
    expect(errorHtml).not.toContain("success");

    const progressHtml = renderToStaticMarkup(
      <StatusStrips
        error=""
        message="success"
        isParsing
        hasSpaceQueueWork
        parseProgress={makeProgress()}
        spaceProgress={makeProgress()}
      />,
    );
    expect(progressHtml).toContain("45%");
    expect(progressHtml).toContain("working");
  });

  it("renders loading, empty and populated video list states", () => {
    expect(
      renderToStaticMarkup(
        <VideoListPanel
          activeDbId="main"
          backendTotalVideoCount={0}
          hasMore={false}
          isLoading
          query=""
          totalVideoCount={0}
          videos={[]}
          onLoadMore={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("正在载入");

    expect(
      renderToStaticMarkup(
        <VideoListPanel
          activeDbId="main"
          backendTotalVideoCount={0}
          hasMore={false}
          isLoading={false}
          query=""
          totalVideoCount={0}
          videos={[]}
          onLoadMore={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("还没有归档任何视频");

    expect(
      renderToStaticMarkup(
        <VideoListPanel
          activeDbId="main"
          backendTotalVideoCount={5}
          hasMore={false}
          isLoading={false}
          query="zzz"
          totalVideoCount={5}
          videos={[]}
          onLoadMore={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("没有匹配的视频");

    const html = renderToStaticMarkup(
      <VideoListPanel
        activeDbId="archive"
        backendTotalVideoCount={1}
        hasMore={false}
        isLoading={false}
        query="test"
        selectedOwnerName="Owner"
        totalVideoCount={1}
        videos={[makeVideo()]}
        onLoadMore={() => undefined}
        onQueryChange={() => undefined}
      />,
    );
    expect(html).toContain("Test video");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).toContain("1 / 1");
  });

  it("virtualizes long video lists instead of rendering every card", () => {
    const videos = Array.from({ length: 40 }, (_item, index) =>
      makeVideo({ bvid: `BV1xx411c${String(index).padStart(3, "0")}`, title: `Video ${index}` }),
    );

    render(
      <VideoListPanel
        activeDbId="main"
        backendTotalVideoCount={45}
        hasMore
        isLoading={false}
        query=""
        totalVideoCount={45}
        videos={videos}
        onLoadMore={() => undefined}
        onQueryChange={() => undefined}
      />,
    );

    expect(screen.getByText("40 / 45")).toBeTruthy();
    expect(screen.getByRole("button", { name: /加载更多视频/ })).toBeTruthy();
    expect(screen.getByText("Video 0")).toBeTruthy();
    // Only a window is mounted; the 40th card must not be in the DOM.
    expect(screen.queryByText("Video 39")).toBeNull();
  });

  it("labels loaded-only statistics so a partial page does not look like the whole library", () => {
    const html = renderToStaticMarkup(
      <LibraryStats
        loadedCount={40}
        scope="library"
        totals={{ views: 1000, comments: 5000, active: 40, deleted: 10, likes: 99, danmaku: 800 }}
        videoCount={120}
      />,
    );

    expect(html).toContain("评论档案（全库）");
    expect(html).toContain("弹幕档案（全库）");
    expect(html).toContain("播放量（已加载 40 条）");
    expect(html).toContain("仍可见 / 未返回（已加载 40 条）");
    expect(html).toContain("评论点赞（已加载 40 条）");
  });

  it("marks a loaded-only comment total in the page header", () => {
    const partial = renderToStaticMarkup(
      <LibraryHeader
        commentCount={5000}
        commentScope="loaded"
        isLoading={false}
        isLoadingDatabases={false}
        loadedCount={40}
        showSettings={false}
        videoCount={120}
        onRefresh={() => undefined}
        onToggleSettings={() => undefined}
      />,
    );
    expect(partial).toContain("条评论档案（已加载 40 条）");

    const whole = renderToStaticMarkup(
      <LibraryHeader
        commentCount={5000}
        commentScope="library"
        isLoading={false}
        isLoadingDatabases={false}
        loadedCount={40}
        showSettings={false}
        videoCount={120}
        onRefresh={() => undefined}
        onToggleSettings={() => undefined}
      />,
    );
    expect(whole).not.toContain("条评论档案（已加载");
  });

  it("warns when part of the library failed to load and offers a retry", () => {
    const html = renderToStaticMarkup(
      <VideoListPanel
        activeDbId="main"
        backendTotalVideoCount={5}
        failedDatabases={[{ id: "db:broken", error: "database is locked" }]}
        hasMore={false}
        incomplete
        isLoading={false}
        query=""
        totalVideoCount={5}
        videos={[makeVideo()]}
        onLoadMore={() => undefined}
        onQueryChange={() => undefined}
        onRetryVideos={() => undefined}
      />,
    );

    expect(html).toContain("数据库读取失败");
    expect(html).toContain("db:broken");
    expect(html).toContain("重试");
  });

  it("renders cookie login diagnostics in settings", () => {
    const html = renderToStaticMarkup(
      <LibrarySidebar
        cookieStatus={makeCookieStatus({
          status: "invalid",
          message: "Bilibili 返回账号未登录",
          is_login: false,
          nav_code: -101,
          nav_message: "账号未登录",
          bili_ticket_expired: true,
        })}
        duplicateVideo={null}
        hasSpaceQueueWork={false}
        hotplugDir="data/databases"
        isParsing={false}
        isSubmittingSpace={false}
        isTaskBusy={false}
        ownerFilter="all"
        ownerGroups={[]}
        ownerRef=""
        parseDelay={1}
        showSettings
        totals={{ comments: 0, danmaku: 0 }}
        url=""
        videoCount={0}
        onDuplicateOpen={() => undefined}
        onDuplicateReparse={() => undefined}
        onOwnerExport={() => undefined}
        onOwnerFilterChange={() => undefined}
        onOwnerRefChange={() => undefined}
        onParseDelayChange={() => undefined}
        onSubmitParse={(event) => event.preventDefault()}
        onSubmitSpaceArchive={(event) => event.preventDefault()}
        onUrlChange={() => undefined}
      />,
    );

    expect(html).toContain("未登录");
    expect(html).toContain("SESSDATA");
    expect(html).toContain("DedeUserID");
    expect(html).toContain("短期票据过期");
  });

  it("renders direct DB and JSON export actions for owner groups", () => {
    const html = renderToStaticMarkup(
      <LibrarySidebar
        cookieStatus={makeCookieStatus()}
        duplicateVideo={null}
        hasSpaceQueueWork={false}
        hotplugDir="data/databases"
        isParsing={false}
        isSubmittingSpace={false}
        isTaskBusy={false}
        ownerFilter="all"
        ownerGroups={[
          {
            bvids: ["BV1xx411c7mD"],
            key: "mid:42",
            name: "Owner",
            ownerMid: "42",
            videoCount: 1,
            commentCount: 20,
            danmakuCount: 8,
          },
        ]}
        ownerRef=""
        parseDelay={1}
        showSettings={false}
        totals={{ comments: 20, danmaku: 8 }}
        url=""
        videoCount={1}
        onDuplicateOpen={() => undefined}
        onDuplicateReparse={() => undefined}
        onOwnerExport={() => undefined}
        onOwnerFilterChange={() => undefined}
        onOwnerRefChange={() => undefined}
        onParseDelayChange={() => undefined}
        onSubmitParse={(event) => event.preventDefault()}
        onSubmitSpaceArchive={(event) => event.preventDefault()}
        onUrlChange={() => undefined}
      />,
    );

    expect(html).toContain("Owner");
    expect(html).toContain("DB");
    expect(html).toContain("JSON");
  });

  it("renders an export notice action for opening the output folder", () => {
    const html = renderToStaticMarkup(
      <NoticeDialog
        notice={{
          kind: "success",
          title: "导出完成",
          message: "data/databases/video.db 已导出",
          actionLabel: "打开所在文件夹",
          onAction: () => undefined,
        }}
        onClose={() => undefined}
      />,
    );

    expect(html).toContain("导出完成");
    expect(html).toContain("打开所在文件夹");
  });
});
