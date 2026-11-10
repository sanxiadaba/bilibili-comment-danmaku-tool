import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  archiveSpaceVideos,
  clearCookie,
  controlSpaceTasks,
  createAuthQrCode,
  deleteArchiveData,
  exportDatabaseArchive,
  fetchDatabases,
  fetchCommentData,
  fetchDanmakuData,
  fetchProgress,
  fetchVideos,
  importDatabase,
  importDatabaseFiles,
  logClientEvent,
  openLocalPath,
  parseVideo,
  pollAuthQrCode,
  refreshCommentData,
  refreshDanmakuData,
  saveCookie,
} from "../../../frontend/src/api/client";
import { installApiBrowserStubs } from "../helpers/browser";

function jsonResponse(payload: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

/** Every API call also emits a telemetry POST; assertions should look at the real request. */
function apiCalls(fetchMock: { mock: { calls: unknown[][] } }) {
  return fetchMock.mock.calls.filter(([url]) => !String(url).startsWith("/api/logs/client"));
}

function firstApiCall(fetchMock: { mock: { calls: unknown[][] } }) {
  return apiCalls(fetchMock)[0] as [string, RequestInit];
}

describe("API client", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-13T00:00:00.000Z"));
    installApiBrowserStubs();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends library search and owner filters to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ videos: [], total: 0 }));
    globalThis.fetch = fetchMock;

    await fetchVideos("main", { query: "测试", ownerKey: "mid:42", limit: 40, offset: 0 });

    const url = firstApiCall(fetchMock)[0];
    expect(url).toContain("q=%E6%B5%8B%E8%AF%95");
    expect(url).toContain("owner=mid%3A42");
  });

  it("omits the owner filter for the all-owners pseudo key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ videos: [], total: 0 }));
    globalThis.fetch = fetchMock;

    await fetchVideos("main", { ownerKey: "all" });

    expect(firstApiCall(fetchMock)[0]).not.toContain("owner=");
  });

  it("adds db ids to list requests and parses JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ videos: [] }));
    globalThis.fetch = fetchMock;

    const payload = await fetchVideos("archive 1", { limit: 40, offset: 80 });

    expect(payload.videos).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/videos?"), expect.objectContaining({ cache: "no-store" }));
    expect(firstApiCall(fetchMock)[0]).toContain("db_id=archive+1");
    expect(firstApiCall(fetchMock)[0]).toContain("limit=40");
    expect(firstApiCall(fetchMock)[0]).toContain("offset=80");
  });

  it("passes abort signals through read requests", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/comments?")) return Promise.resolve(jsonResponse({ metadata: {}, comments: [], comment_items: [] }));
      if (url.includes("/api/danmaku?")) return Promise.resolve(jsonResponse({ metadata: {}, items: [] }));
      return Promise.resolve(jsonResponse({ videos: [] }));
    });
    globalThis.fetch = fetchMock;
    const controller = new AbortController();

    await fetchVideos("archive", { signal: controller.signal });
    await fetchCommentData("BV1xx411c7mD", "archive", { signal: controller.signal });
    await fetchDanmakuData("BV1xx411c7mD", "archive", { signal: controller.signal });

    // Requests are also bounded by a timeout, so the caller signal is combined with it rather
    // than passed through by identity; what matters is that aborting it cancels the request.
    expect(firstApiCall(fetchMock)[1].signal).not.toBeUndefined();
    expect(apiCalls(fetchMock)[1][1].signal).not.toBeUndefined();
    expect(apiCalls(fetchMock)[2][1].signal).not.toBeUndefined();

    controller.abort();
    expect(firstApiCall(fetchMock)[1].signal?.aborted).toBe(true);
    expect(apiCalls(fetchMock)[1][1].signal?.aborted).toBe(true);
    expect(apiCalls(fetchMock)[2][1].signal?.aborted).toBe(true);
  });

  it("can skip heavy video metadata on append requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ videos: [] }));
    globalThis.fetch = fetchMock;

    await fetchVideos("main", { includeMeta: false, limit: 40, offset: 40 });

    expect(firstApiCall(fetchMock)[0]).toContain("include_meta=0");
  });

  it("can skip heavy database catalog details", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ databases: [] }));
    globalThis.fetch = fetchMock;

    await fetchDatabases("main", { includeDetails: false });

    expect(firstApiCall(fetchMock)[0]).toContain("/api/databases?");
    expect(firstApiCall(fetchMock)[0]).toContain("include_details=0");
  });

  it("sends parse, space archive, import and export payloads", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true, videos: [], bvid: "BV1xx411c7mD" })));
    globalThis.fetch = fetchMock;

    await parseVideo("BV1xx411c7mD", 0.5, "main");
    await archiveSpaceVideos("https://space.bilibili.com/123456", { delay: 1, dbId: "main" });
    await controlSpaceTasks("pause", "space-1");
    await importDatabase("D:/archive.json");
    await exportDatabaseArchive({ format: "json", bvid: "BV1xx411c7mD", db_id: "main" });
    await openLocalPath("D:/data/databases");
    await deleteArchiveData({ bvid: "BV1xx411c7mD", db_id: "main" });

    expect(JSON.parse(firstApiCall(fetchMock)[1].body as string)).toMatchObject({
      url: "BV1xx411c7mD",
      delay: 0.5,
      db_id: "main",
    });
    expect(JSON.parse(apiCalls(fetchMock)[1][1].body as string)).toMatchObject({
      owner_ref: "https://space.bilibili.com/123456",
      delay: 1,
      db_id: "main",
    });
    expect(JSON.parse(apiCalls(fetchMock)[2][1].body as string)).toEqual({ action: "pause", task_id: "space-1" });
    expect(JSON.parse(apiCalls(fetchMock)[3][1].body as string)).toEqual({ path: "D:/archive.json" });
    expect(JSON.parse(apiCalls(fetchMock)[4][1].body as string)).toMatchObject({
      format: "json",
      bvid: "BV1xx411c7mD",
    });
    expect(apiCalls(fetchMock)[5][0]).toContain("/api/system/open-path?");
    expect(JSON.parse(apiCalls(fetchMock)[5][1].body as string)).toEqual({ path: "D:/data/databases" });
    expect(apiCalls(fetchMock)[6][0]).toContain("/api/archive/delete?");
    expect(JSON.parse(apiCalls(fetchMock)[6][1].body as string)).toMatchObject({
      bvid: "BV1xx411c7mD",
      db_id: "main",
    });
  });

  it("scopes comment and danmaku reads or refreshes by bvid and database", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    globalThis.fetch = fetchMock;

    await fetchCommentData("BV1xx411c7mD", "archive", { limit: 500, offset: 100 });
    await refreshCommentData("BV1xx411c7mD", "archive");
    await fetchDanmakuData("BV1xx411c7mD", "archive");
    await refreshDanmakuData("BV1xx411c7mD", "archive");

    expect(firstApiCall(fetchMock)[0]).toContain("/api/comments?");
    expect(firstApiCall(fetchMock)[0]).toContain("bvid=BV1xx411c7mD");
    expect(firstApiCall(fetchMock)[0]).toContain("db_id=archive");
    expect(firstApiCall(fetchMock)[0]).toContain("limit=500");
    expect(firstApiCall(fetchMock)[0]).toContain("offset=100");
    expect(apiCalls(fetchMock)[1][0]).toContain("/api/refresh?");
    expect(apiCalls(fetchMock)[1][1]).toMatchObject({ method: "POST" });
    expect((apiCalls(fetchMock)[1][1].headers as Headers).get("X-Bilibili-Tool-Request")).toBe("1");
    expect(apiCalls(fetchMock)[2][0]).toContain("/api/danmaku?");
    expect(apiCalls(fetchMock)[2][0]).not.toContain("limit=");
    expect(apiCalls(fetchMock)[3][0]).toContain("/api/danmaku/refresh?");
    expect(apiCalls(fetchMock)[3][1]).toMatchObject({ method: "POST" });
  });

  it("supports optional danmaku limits for control callers", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    globalThis.fetch = fetchMock;

    await fetchDanmakuData("BV1xx411c7mD", "archive", { limit: 2000 });

    expect(firstApiCall(fetchMock)[0]).toContain("/api/danmaku?");
    expect(firstApiCall(fetchMock)[0]).toContain("limit=2000");
  });

  it("adds the local browser guard header to mutating requests", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true, bvid: "BV1xx411c7mD" })));
    globalThis.fetch = fetchMock;

    await parseVideo("BV1xx411c7mD", 0.5, "main");
    await importDatabaseFiles([new File(["payload"], "archive.json")]);

    expect((firstApiCall(fetchMock)[1].headers as Headers).get("X-Bilibili-Tool-Request")).toBe("1");
    expect((apiCalls(fetchMock)[1][1].headers as Headers).get("X-Bilibili-Tool-Request")).toBe("1");
  });

  it("preserves caller headers while adding the local browser guard header", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    globalThis.fetch = fetchMock;

    await saveCookie("SESSDATA=session; bili_jct=csrf");
    await pollAuthQrCode("session-1234567890");

    const saveHeaders = firstApiCall(fetchMock)[1].headers as Headers;
    const pollHeaders = apiCalls(fetchMock)[1][1].headers as Headers;
    expect(saveHeaders.get("Content-Type")).toBe("application/json");
    expect(saveHeaders.get("X-Bilibili-Tool-Request")).toBe("1");
    expect(pollHeaders.get("Content-Type")).toBe("application/json");
    expect(pollHeaders.get("X-Bilibili-Tool-Request")).toBe("1");
  });

  it("does not add the local browser guard header to readonly requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ videos: [] }));
    globalThis.fetch = fetchMock;

    await fetchVideos("main");

    expect(firstApiCall(fetchMock)[1].headers).toBeUndefined();
  });

  it("uploads selected database files as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock;
    const file = new File(["payload"], "archive.json", { type: "application/json" });

    await importDatabaseFiles([file]);

    const requestInit = firstApiCall(fetchMock)[1];
    expect(firstApiCall(fetchMock)[0]).toContain("/api/databases/import-file?");
    expect(requestInit.method).toBe("POST");
    expect(requestInit.body).toBeInstanceOf(FormData);
    const uploadedFile = Array.from((requestInit.body as FormData).getAll("files"))[0] as File;
    expect(uploadedFile.name).toBe(file.name);
    expect(uploadedFile.type).toBe(file.type);
    expect(uploadedFile.size).toBe(file.size);
  });

  it("sends local auth management requests", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    globalThis.fetch = fetchMock;

    await saveCookie("SESSDATA=session; bili_jct=csrf");
    await clearCookie();
    await createAuthQrCode();
    await pollAuthQrCode("session-1234567890");

    expect(firstApiCall(fetchMock)[0]).toContain("/api/cookie/save?");
    expect(JSON.parse(firstApiCall(fetchMock)[1].body as string)).toEqual({ cookie: "SESSDATA=session; bili_jct=csrf" });
    expect(apiCalls(fetchMock)[1][0]).toContain("/api/cookie/clear?");
    expect(apiCalls(fetchMock)[1][1]).toMatchObject({ method: "POST" });
    expect(apiCalls(fetchMock)[2][0]).toContain("/api/auth/qrcode?");
    expect(apiCalls(fetchMock)[2][1]).toMatchObject({ method: "POST" });
    expect(apiCalls(fetchMock)[3][0]).toContain("/api/auth/qrcode/poll?");
    expect(JSON.parse(apiCalls(fetchMock)[3][1].body as string)).toEqual({ session_id: "session-1234567890" });
  });

  it("reports JSON API errors and HTML fallback responses clearly", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(jsonResponse({ error: "bad request" }, { status: 400 }));
    await expect(fetchProgress()).rejects.toThrow("bad request");

    globalThis.fetch = vi.fn().mockResolvedValueOnce(
      new Response("<!doctype html><html></html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(fetchProgress()).rejects.toThrow(/API/);
  });

  it("turns a request timeout into a readable error", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new DOMException("timeout", "TimeoutError"))) as typeof fetch;

    await expect(fetchVideos("main", { limit: 40 })).rejects.toThrow(/请求超时/);
  });

  it("sends client logs with the local guard header", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock;

    logClientEvent("client.test", "hello", { bvid: "BV1xx411c7mD" });

    const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/logs/client") as [string, RequestInit];
    expect(call).toBeTruthy();
    const headers = new Headers(call[1].headers);
    expect(headers.get("X-Bilibili-Tool-Request")).toBe("1");
    expect(call[1].method).toBe("POST");
  });

  it("ignores client log failures", () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("network down"))) as typeof fetch;

    expect(() => logClientEvent("client.test", "ignored")).not.toThrow();
  });
});
