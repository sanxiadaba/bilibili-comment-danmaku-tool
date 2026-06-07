import { describe, expect, it } from "vitest";
import type { DanmakuItem } from "../../types";
import {
  buildDanmakuBuckets,
  buildDanmakuColorStats,
  buildDanmakuModeStats,
  buildRepeatedDanmakuContent,
  colorNameForDanmaku,
  colorNumberToHex,
  formatProgress,
  getDanmakuModeGroup,
  getDanmakuModeLabel,
  sortDanmakuItems,
} from "./danmakuUtils";

function makeDanmaku(overrides: Partial<DanmakuItem> = {}): DanmakuItem {
  return {
    dmid: "1",
    bvid: "BV1xx411c7mD",
    cid: "456",
    progress: 0,
    mode: 1,
    font_size: 25,
    color: 0xffffff,
    ctime: 1700000000,
    pool: 0,
    user_hash: "hash",
    weight: 0,
    like_count: 0,
    is_up_owner: false,
    content: "hello",
    fetched_at: "2024-01-01T00:00:00+00:00",
    ...overrides,
  };
}

describe("danmaku utilities", () => {
  it("formats progress and sorts by supported modes", () => {
    const items = [
      makeDanmaku({ dmid: "1", progress: 12, like_count: 3, ctime: 100, content: "beta" }),
      makeDanmaku({ dmid: "2", progress: 3, like_count: 8, ctime: 120, content: "alpha" }),
      makeDanmaku({ dmid: "3", progress: 12, like_count: 8, ctime: 90, content: "gamma" }),
    ];

    expect(formatProgress(125.9)).toBe("02:05");
    expect(sortDanmakuItems(items, "progress_asc").map((item) => item.dmid)).toEqual(["2", "1", "3"]);
    expect(sortDanmakuItems(items, "progress_desc").map((item) => item.dmid)).toEqual(["3", "1", "2"]);
    expect(sortDanmakuItems(items, "like_desc").map((item) => item.dmid)).toEqual(["2", "3", "1"]);
    expect(sortDanmakuItems(items, "time_desc").map((item) => item.dmid)).toEqual(["2", "1", "3"]);
    expect(sortDanmakuItems(items, "content_asc").map((item) => item.dmid)).toEqual(["2", "1", "3"]);
  });

  it("builds timeline, mode, color and repeated-content statistics", () => {
    const items = [
      makeDanmaku({ dmid: "1", progress: 3, mode: 1, color: 0xffffff, content: "same" }),
      makeDanmaku({ dmid: "2", progress: 15, mode: 5, color: 0xfe0302, content: "same" }),
      makeDanmaku({ dmid: "3", progress: 17, mode: 4, color: 0xfe0302, content: "other" }),
      makeDanmaku({ dmid: "4", progress: 29, mode: 9, color: 0x123456, content: " " }),
    ];

    expect(buildDanmakuBuckets(items)).toEqual([
      { bucket_start: 0, label: "00:00", count: 1 },
      { bucket_start: 10, label: "00:10", count: 2 },
      { bucket_start: 20, label: "00:20", count: 1 },
    ]);
    expect(buildDanmakuModeStats(items).map((item) => [item.mode, item.count])).toEqual([
      ["scroll", 1],
      ["top", 1],
      ["bottom", 1],
      ["other", 1],
    ]);
    expect(buildDanmakuColorStats(items).map((item) => [item.color, item.count])).toEqual([
      [0xfe0302, 2],
      [0x123456, 1],
      [0xffffff, 1],
    ]);
    expect(buildRepeatedDanmakuContent(items)).toMatchObject([{ content: "same", count: 2 }]);
  });

  it("maps modes and colors to stable display values", () => {
    expect(getDanmakuModeGroup(1)).toBe("scroll");
    expect(getDanmakuModeGroup(5)).toBe("top");
    expect(getDanmakuModeGroup(4)).toBe("bottom");
    expect(getDanmakuModeGroup(9)).toBe("other");
    expect(getDanmakuModeLabel(9)).toContain("9");
    expect(colorNumberToHex(0xfe0302)).toBe("#FE0302");
    expect(colorNumberToHex(0xffffff + 1)).toBe("#FFFFFF");
    expect(colorNumberToHex(-1)).toBe("#000000");
    expect(colorNameForDanmaku(0xffffff)).not.toBe("");
    expect(colorNameForDanmaku(0x123456)).not.toBe("");
  });
});
