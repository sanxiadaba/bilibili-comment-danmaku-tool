import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LibraryStats } from "../../../../frontend/src/components/video-library/LibraryStats";
import { StatusStrips } from "../../../../frontend/src/components/video-library/StatusStrips";
import { VideoListPanel } from "../../../../frontend/src/components/video-library/VideoListPanel";
import { makeProgress, makeVideo } from "../../helpers/factories";

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
          exportingKey=""
          isLoading
          query=""
          totalVideoCount={0}
          videos={[]}
          onExport={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("正在载入");

    expect(
      renderToStaticMarkup(
        <VideoListPanel
          activeDbId="main"
          exportingKey=""
          isLoading={false}
          query=""
          totalVideoCount={0}
          videos={[]}
          onExport={() => undefined}
          onQueryChange={() => undefined}
        />,
      ),
    ).toContain("暂无");

    const html = renderToStaticMarkup(
      <VideoListPanel
        activeDbId="archive"
        exportingKey="video:BV1xx411c7mD"
        isLoading={false}
        query="test"
        selectedOwnerName="Owner"
        totalVideoCount={1}
        videos={[makeVideo()]}
        onExport={() => undefined}
        onQueryChange={() => undefined}
      />,
    );
    expect(html).toContain("Test video");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).toContain("1 / 1");
  });
});
