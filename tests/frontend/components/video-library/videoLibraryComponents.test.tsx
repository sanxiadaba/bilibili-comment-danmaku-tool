import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LibraryStats } from "../../../../frontend/src/components/video-library/LibraryStats";
import { LibrarySidebar } from "../../../../frontend/src/components/video-library/LibrarySidebar";
import { StatusStrips } from "../../../../frontend/src/components/video-library/StatusStrips";
import { NoticeDialog } from "../../../../frontend/src/components/video-library/NoticeDialog";
import { VideoListPanel } from "../../../../frontend/src/components/video-library/VideoListPanel";
import { makeCookieStatus, makeProgress, makeVideo } from "../../helpers/factories";

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
    ).toContain("暂无");

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

  it("renders a backend pagination affordance for large video lists", () => {
    const videos = Array.from({ length: 40 }, (_item, index) =>
      makeVideo({ bvid: `BV1xx411c${String(index).padStart(3, "0")}`, title: `Video ${index}` }),
    );

    const html = renderToStaticMarkup(
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

    expect(html).toContain("40 / 45");
    expect(html).toContain("加载更多视频");
    expect(html).toContain("Video 39");
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
