import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BarChart3 } from "lucide-react";
import { DetailMetric, InfoRow, Metric, OwnerBadge, ProgressBanner } from "../../../frontend/src/components/common";
import { makeProgress } from "../helpers/factories";

describe("common components", () => {
  it("renders compact metrics and info rows with formatted values", () => {
    const html = renderToStaticMarkup(
      <>
        <Metric icon={BarChart3} label="Views" value={12345} />
        <DetailMetric icon={BarChart3} label="Mode" value="Scroll" />
        <InfoRow label="bvid" value="BV1xx411c7mD" />
        <OwnerBadge />
      </>,
    );

    expect(html).toContain("Views");
    expect(html).toContain("1.2万");
    expect(html).toContain("Scroll");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).toContain("UP");
  });

  it("clamps progress percent, limits logs and keeps fallback state readable", () => {
    const html = renderToStaticMarkup(
      <ProgressBanner
        fallback="waiting"
        progress={makeProgress({
          percent: 150,
          logs: ["first", "second", "third", "fourth", "fifth"],
          stats: { A: 1, B: 2, C: 3, D: 4, E: 5, F: 6, G: 7 },
        })}
      />,
    );

    expect(html).toContain("100%");
    expect(html).toContain("width:100%");
    expect(html).not.toContain("first");
    expect(html).toContain("second");
    expect(html).not.toContain(">G<");

    const fallbackHtml = renderToStaticMarkup(<ProgressBanner fallback="waiting" progress={null} />);
    expect(fallbackHtml).toContain("8%");
    expect(fallbackHtml).toContain("waiting");
  });
});
