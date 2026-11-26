import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  batchExportLabel,
  buildOwnerGroups,
  databaseIdForDeleteTarget,
  dbPath,
  deletePayloadForTarget,
  deleteRequestsForTarget,
  deleteTargetVideoCount,
  exportDatabaseIdForVideos,
  extractBvid,
  findVideoByBvid,
  formatBytes,
  initialDatabaseId,
  mergeVideosByBvid,
  ownerKey,
  ownerName,
  refreshLoadedVideos,
  singleDatabaseIdForVideos,
  summarizeLibrary,
  summarizeOwnerRef,
  summarizeVideos,
  videoExportLabel,
} from "../../../frontend/src/lib/videoLibrary";
import { installWindowStub } from "../helpers/browser";
import { makeVideo } from "../helpers/factories";
import type { OwnerGroup } from "../../../frontend/src/types";

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
    expect(ownerKey(makeVideo({ owner_mid: "", owner_name: "Alice" }))).toBe("name:Alice");
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

  it("refreshes the first page without dropping already loaded pages", () => {
    const loaded = [
      makeVideo({ bvid: "BV1A", title: "stale" }),
      makeVideo({ bvid: "BV1B" }),
      makeVideo({ bvid: "BV1C" }),
      makeVideo({ bvid: "BV1D" }),
      makeVideo({ bvid: "BV1E" }),
    ];
    const firstPage = [makeVideo({ bvid: "BV1New", title: "newest" }), makeVideo({ bvid: "BV1A", title: "fresh" })];

    const refreshed = refreshLoadedVideos(loaded, firstPage);
    expect(refreshed.map((video) => video.bvid)).toEqual(["BV1New", "BV1A", "BV1B", "BV1C", "BV1D", "BV1E"]);
    expect(refreshed[1].title).toBe("fresh");
    expect(refreshed).toHaveLength(loaded.length + 1);
  });

  it("summarizes library totals", () => {
    const videos = [
      makeVideo({ bvid: "BV1Alpha001", title: "Alpha", owner_mid: "42", owner_name: "Alice", stat_view: 10, comment_total_count: 2, active_comment_count: 1, deleted_comment_count: 1, comment_like_count: 5, danmaku_count: 7 }),
      makeVideo({ bvid: "BV1Beta0001", title: "Beta", owner_mid: "7", owner_name: "Bob", stat_view: 20, comment_total_count: 3, active_comment_count: 3, deleted_comment_count: 0, comment_like_count: 6, danmaku_count: 8 }),
    ];

    expect(summarizeVideos(videos)).toEqual({ views: 30, comments: 5, active: 4, deleted: 1, likes: 11, danmaku: 15 });
  });

  it("prefers whole-library owner totals and falls back to the loaded page", () => {
    const videos = [
      makeVideo({ bvid: "BV1Alpha001", stat_view: 10, comment_total_count: 2, active_comment_count: 1, deleted_comment_count: 1, comment_like_count: 5, danmaku_count: 7 }),
    ];
    const owners = [
      { key: "mid:42", name: "Alice", owner_mid: "42", video_count: 60, comment_count: 1200, danmaku_count: 340 },
      { key: "name:guest", name: "Guest", owner_mid: "", video_count: 2, comment_count: 30, danmaku_count: 9 },
    ];

    expect(summarizeLibrary(videos, owners)).toEqual({
      views: 10,
      comments: 1230,
      active: 1,
      deleted: 1,
      likes: 5,
      danmaku: 349,
      scope: "library",
    });
    expect(summarizeLibrary(videos)).toMatchObject({ comments: 2, danmaku: 7, scope: "loaded" });
  });

  it("finds a video by bvid regardless of case", () => {
    const videos = [makeVideo({ bvid: "BV1xx411c7mD" })];
    expect(findVideoByBvid(videos, "bv1XX411c7Md")).toBe(videos[0]);
    expect(findVideoByBvid(videos, "BV1Other0000")).toBeUndefined();
    expect(findVideoByBvid(videos, "  ")).toBeUndefined();
  });

  it("resolves the export scope to one database or the aggregate view", () => {
    expect(exportDatabaseIdForVideos([makeVideo({ db_id: "db:a" })], "db:a")).toBe("db:a");
    expect(exportDatabaseIdForVideos([makeVideo({ db_id: "" })], "db:fallback")).toBe("db:fallback");
    expect(
      exportDatabaseIdForVideos([makeVideo({ db_id: "db:a" }), makeVideo({ bvid: "BV1Second001", db_id: "db:b" })], "db:a"),
    ).toBe("main");
  });

  it("builds export labels and delete request helpers", () => {
    const owner = buildOwnerGroups([
      makeVideo({ bvid: "BV1Delete001", owner_mid: "", owner_name: "Guest" }),
      makeVideo({ bvid: "BV1Delete002", owner_mid: "", owner_name: "Guest" }),
    ])[0];
    const video = makeVideo({ bvid: "BV1Delete003", title: "", db_id: "db-video" });

    expect(videoExportLabel(video)).toBe("未命名视频");
    expect(batchExportLabel("批量视频", ["A", "B", "C"], 3)).toBe("批量视频_A_B_等3项");
    expect(deletePayloadForTarget({ kind: "video", video })).toEqual({ bvid: "BV1Delete003" });
    expect(deletePayloadForTarget({ kind: "owners", owners: [owner] })).toEqual({ bvids: ["BV1Delete001", "BV1Delete002"] });
    expect(databaseIdForDeleteTarget({ kind: "video", video }, "main")).toBe("db-video");
    expect(databaseIdForDeleteTarget({ kind: "videos", videos: [makeVideo({ db_id: "db-a" }), makeVideo({ bvid: "BV1Delete004", db_id: "db-b" })] }, "main")).toBe("");
    expect(deleteTargetVideoCount({ kind: "owners", owners: [owner] })).toBe(2);
  });

  it("does not call global timers or network while computing helper values", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch" as never);
    extractBvid("BV1xx411c7mD");
    formatBytes(2048);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("plans one delete request per database and refuses owner deletes in the aggregate view", () => {
    const first = makeVideo({ bvid: "BV1Alpha001", db_id: "db:a" });
    const second = makeVideo({ bvid: "BV1Beta0001", db_id: "db:b" });
    const owner = buildOwnerGroups([makeVideo({ owner_mid: "42", owner_name: "Alice" })])[0];

    expect(deleteRequestsForTarget({ kind: "videos", videos: [first, second] }, "main")).toEqual([
      { db_id: "db:a", bvids: ["BV1Alpha001"] },
      { db_id: "db:b", bvids: ["BV1Beta0001"] },
    ]);
    expect(deleteRequestsForTarget({ kind: "owner", owner }, "main")).toEqual([]);
    expect(deleteRequestsForTarget({ kind: "owner", owner }, "db:a")).toEqual([{ db_id: "db:a", owner_mid: "42" }]);

    const groups = buildOwnerGroups(
      [
        makeVideo({ bvid: "BV1OwnerA01", owner_mid: "42", owner_name: "Alice" }),
        makeVideo({ bvid: "BV1OwnerB01", owner_mid: "7", owner_name: "Bob" }),
      ],
      [
        { key: "mid:42", name: "Alice", owner_mid: "42", video_count: 1, comment_count: 1, danmaku_count: 0, storage_bytes: 0 },
        { key: "mid:7", name: "Bob", owner_mid: "7", video_count: 1, comment_count: 1, danmaku_count: 0, storage_bytes: 0 },
      ],
    );
    expect(deleteRequestsForTarget({ kind: "owners", owners: groups }, "db:a")).toEqual([
      { db_id: "db:a", owner_mid: "42" },
      { db_id: "db:a", owner_mid: "7" },
    ]);
  });

  it("splits mixed owner deletes instead of silently skipping owners with a mid", () => {
    const midOwner: OwnerGroup = {
      bvids: [],
      key: "mid:42",
      name: "Alice",
      ownerMid: "42",
      videoCount: 3,
      commentCount: 10,
      danmakuCount: 2,
    };
    const guestOwner: OwnerGroup = {
      bvids: ["BV1Guest001", "BV1Guest002"],
      key: "name:Guest",
      name: "Guest",
      ownerMid: "",
      videoCount: 2,
      commentCount: 4,
      danmakuCount: 0,
    };
    const otherGuest: OwnerGroup = {
      bvids: ["BV1Guest002", "BV1Guest003"],
      key: "name:Other",
      name: "Other",
      ownerMid: "",
      videoCount: 2,
      commentCount: 1,
      danmakuCount: 0,
    };

    expect(deleteRequestsForTarget({ kind: "owners", owners: [midOwner, guestOwner, otherGuest] }, "db:a")).toEqual([
      { db_id: "db:a", owner_mid: "42" },
      { db_id: "db:a", bvids: ["BV1Guest001", "BV1Guest002", "BV1Guest003"] },
    ]);
    expect(deleteRequestsForTarget({ kind: "owner", owner: guestOwner }, "db:a")).toEqual([
      { db_id: "db:a", bvids: ["BV1Guest001", "BV1Guest002"] },
    ]);
    expect(
      deleteRequestsForTarget(
        { kind: "owners", owners: [{ ...otherGuest, bvids: [], videoCount: 0 }] },
        "db:a",
      ),
    ).toEqual([]);
  });
});
