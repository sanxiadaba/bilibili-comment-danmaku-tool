import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dbPath, extractBvid, formatBytes, initialDatabaseId, ownerKey, ownerName, summarizeOwnerRef } from "../../../frontend/src/lib/videoLibrary";
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

  it("does not call global timers or network while computing helper values", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch" as never);
    extractBvid("BV1xx411c7mD");
    formatBytes(2048);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
