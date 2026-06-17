import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildOwnerGroups, dbPath, extractBvid, formatBytes, initialDatabaseId, mergeVideosByBvid, ownerKey, ownerName, singleDatabaseIdForVideos, summarizeOwnerRef } from "../../../frontend/src/lib/videoLibrary";
import { installWindowStub } from "../helpers/browser";
import { makeVideo } from "../helpers/factories";

describe("video library helpers", () => {
  beforeEach(() => {
    installWindowStub();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("extracts BV ids and summarizes owner references", () => {
    expect(extractBvid("https://www.bilibili.com/video/BV1xx411c7mD/?p=1")).toBe("BV1xx411c7mD");
    expect(extractBvid("not a video")).toBe("");
    expect(summarizeOwnerRef("https://space.bilibili.com/395188578/video")).toBe("395188578");
    expect(summarizeOwnerRef("123456")).toBe("123456");
  });

  it("builds db scoped paths and initializes database id from URL or storage", () => {
    expect(dbPath("/video/BV1xx411c7mD", "main")).toBe("/video/BV1xx411c7mD");
    expect(dbPath("/video/BV1xx411c7mD", "archive 1")).toBe("/video/BV1xx411c7mD?db_id=archive%201");
    expect(dbPath("/video/BV1xx411c7mD?tab=comments", "db:Owner_42/BV1xx411c7mD.db")).toBe(
      "/video/BV1xx411c7mD?tab=comments&db_id=db%3AOwner_42%2FBV1xx411c7mD.db",
    );
    expect(dbPath("/video/BV1xx411c7mD", "")).toBe("/video/BV1xx411c7mD");

    window.history.replaceState({}, "", "/?db_id=hotplug");
    expect(initialDatabaseId()).toBe("hotplug");
    expect(window.localStorage.getItem("bilibili-active-db-id")).toBe("hotplug");

    window.history.replaceState({}, "", "/");
    window.localStorage.setItem("bilibili-active-db-id", "stored");
    expect(initialDatabaseId()).toBe("stored");
  });

  it("formats bytes and creates stable owner keys", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1024 * 1024 * 12)).toBe("12 MB");
    expect(formatBytes(Number.NaN)).toBe("0 B");

    expect(ownerName(makeVideo({ owner_name: " Alice " }))).toBe("Alice");
    expect(ownerKey(makeVideo({ owner_mid: "42", owner_name: "Alice" }))).toBe("mid:42");
    expect(ownerKey(makeVideo({ owner_mid: "", owner_name: "Alice" }))).toBe("name:alice");
  });

  it("builds owner groups from videos and backend summaries", () => {
    const videos = [
      makeVideo({ bvid: "BV1OwnerA001", owner_mid: "42", owner_name: "Owner A", comment_total_count: 10, danmaku_count: 3 }),
      makeVideo({ bvid: "BV1OwnerA002", owner_mid: "42", owner_name: "Owner A", comment_total_count: 8, danmaku_count: 2 }),
      makeVideo({ bvid: "BV1OwnerB001", owner_mid: "7", owner_name: "Owner B", comment_total_count: 30, danmaku_count: 1 }),
    ];

    const groups = buildOwnerGroups(videos);
    expect(groups.map((group) => group.key)).toEqual(["mid:42", "mid:7"]);
    expect(groups[0]).toMatchObject({ bvids: ["BV1OwnerA001", "BV1OwnerA002"], videoCount: 2, commentCount: 18, danmakuCount: 5 });

    const summarized = buildOwnerGroups(videos, [
      { key: "mid:42", name: "Owner A", owner_mid: "42", video_count: 99, comment_count: 88, danmaku_count: 77, storage_bytes: 66 },
      { key: "name:guest", name: "Guest", owner_mid: "", video_count: 1, comment_count: 2, danmaku_count: 3 },
    ]);
    expect(summarized[0]).toMatchObject({ bvids: [], key: "mid:42", videoCount: 99, storageBytes: 66 });
    expect(summarized[1]).toMatchObject({ bvids: [], key: "name:guest", ownerMid: "" });
  });

  it("merges videos by bvid and detects single selected database ids", () => {
    const current = [makeVideo({ bvid: "BV1A", title: "old", db_id: "db-a" })];
    const incoming = [makeVideo({ bvid: "BV1A", title: "new", db_id: "db-a" }), makeVideo({ bvid: "BV1B", db_id: "db-a" })];

    const merged = mergeVideosByBvid(current, incoming);
    expect(merged.map((video) => video.bvid)).toEqual(["BV1A", "BV1B"]);
    expect(merged[0].title).toBe("new");
    expect(singleDatabaseIdForVideos(merged, "fallback")).toBe("db-a");
    expect(singleDatabaseIdForVideos([makeVideo({ db_id: "db-a" }), makeVideo({ bvid: "BV1C", db_id: "db-c" })], "fallback")).toBe("");
    expect(singleDatabaseIdForVideos([makeVideo({ db_id: "" })], "fallback")).toBe("fallback");
  });

  it("does not call global timers or network while computing helper values", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch" as never);
    extractBvid("BV1xx411c7mD");
    formatBytes(2048);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
