import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ColorSwatch } from "../../../../frontend/src/components/danmaku/ColorSwatch";
import { DanmakuDetail } from "../../../../frontend/src/components/danmaku/DanmakuDetail";
import { DanmakuListRow } from "../../../../frontend/src/components/danmaku/DanmakuList";
import { makeDanmaku } from "../../helpers/factories";

describe("danmaku components", () => {
  it("renders color names through swatches rather than raw user hashes", () => {
    const html = renderToStaticMarkup(<ColorSwatch color={0xfe0302} />);

    expect(html).toContain("#FE0302");
    expect(html).not.toContain("hash");
  });

  it("renders list rows with time, likes and owner marking", () => {
    const item = makeDanmaku({ progress: 65, content: "hello danmaku", like_count: 7, is_up_owner: true });

    const html = renderToStaticMarkup(<DanmakuListRow active item={item} onSelect={() => undefined} />);

    expect(html).toContain("01:05");
    expect(html).toContain("hello danmaku");
    expect(html).toContain("7");
    expect(html).toContain("UP");
  });

  it("renders detail identifiers without showing user_hash", () => {
    const item = makeDanmaku({ dmid: "9001", user_hash: "secret-user-hash", content: "detail danmaku" });

    const html = renderToStaticMarkup(<DanmakuDetail item={item} />);

    expect(html).toContain("detail danmaku");
    expect(html).toContain("9001");
    expect(html).toContain("BV1xx411c7mD");
    expect(html).not.toContain("secret-user-hash");
  });
});
