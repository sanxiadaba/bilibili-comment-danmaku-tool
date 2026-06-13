import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LibraryStats } from "../../../../frontend/src/components/video-library/LibraryStats";
import { LibrarySidebar } from "../../../../frontend/src/components/video-library/LibrarySidebar";
import { StatusStrips } from "../../../../frontend/src/components/video-library/StatusStrips";
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
          exportingKey=""
          hasMore={false}
          isLoading
          query=""
          totalVideoCount={0}
          videos={[]}
          onDelete={() => undefined}
          onExport={() => undefined}
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
          exportingKey=""
          hasMore={false}
          isLoading={false}
          query=""
          totalVideoCount={0}
          videos={[]}
          onDelete={() => undefined}
          onExport={() => undefined}
          onLoadMore={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("暂无");

    const html = renderToStaticMarkup(
      <VideoListPanel
        activeDbId="archive"
        backendTotalVideoCount={1}
        exportingKey="video:BV1xx411c7mD"
        hasMore={false}
        isLoading={false}
        query="test"
        selectedOwnerName="Owner"
        totalVideoCount={1}
        videos={[makeVideo()]}
        onDelete={() => undefined}
        onExport={() => undefined}
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
        exportingKey=""
        hasMore
        isLoading={false}
        query=""
        totalVideoCount={45}
        videos={videos}
        onDelete={() => undefined}
        onExport={() => undefined}
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
        exportingKey=""
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
        onOwnerDelete={() => undefined}
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
});
