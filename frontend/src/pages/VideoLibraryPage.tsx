import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import {
  archiveSpaceVideos,
  controlSpaceTasks,
  deleteArchiveData,
  exportDatabaseArchive,
  fetchCookieStatus,
  fetchDatabases,
  fetchVideos,
  importDatabase,
  importDatabaseFiles,
  logClientEvent,
  openLocalPath,
  parseVideo,
  type TaskControlAction,
} from "../api/client";
import { ExportChoiceDialog } from "../components/video-library/ExportChoiceDialog";
import { AuthPanel } from "../components/video-library/AuthPanel";
import { BatchManagementPanel } from "../components/video-library/BatchManagementPanel";
import { DeleteConfirmDialog } from "../components/video-library/DeleteConfirmDialog";
import { LibraryHeader } from "../components/video-library/LibraryHeader";
import { LibrarySidebar } from "../components/video-library/LibrarySidebar";
import { LibraryStats } from "../components/video-library/LibraryStats";
import { LibraryTabs } from "../components/video-library/LibraryTabs";
import { ManagementPanel } from "../components/video-library/ManagementPanel";
import { NoticeDialog } from "../components/video-library/NoticeDialog";
import { StatusStrips } from "../components/video-library/StatusStrips";
import { TaskManagementPanel } from "../components/video-library/TaskManagementPanel";
import type { DeleteTarget, ExportFormat, ExportTarget, LibraryView, ManagementView, NoticeState, OwnerGroup } from "../components/video-library/types";
import { VideoListPanel } from "../components/video-library/VideoListPanel";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { dbPath, extractBvid, formatBytes, initialDatabaseId, ownerKey, ownerName, summarizeOwnerRef } from "../lib/videoLibrary";
import type { CookieStatus, DatabaseInfo, OwnerSummary, ProgressQueue, ProgressState, ProgressTask, VideoSummary } from "../types";

const VIDEO_PAGE_SIZE = 40;

export function VideoLibraryPage() {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [ownerSummaries, setOwnerSummaries] = useState<OwnerSummary[]>([]);
  const [videoTotal, setVideoTotal] = useState(0);
  const [hasMoreVideos, setHasMoreVideos] = useState(false);
  const [databases, setDatabases] = useState<DatabaseInfo[]>([]);
  const [cookieStatus, setCookieStatus] = useState<CookieStatus | null>(null);
  const [activeDbId, setActiveDbId] = useState(() => initialDatabaseId());
  const [hotplugDir, setHotplugDir] = useState("data/databases");
  const [legacyExportDir, setLegacyExportDir] = useState("data/exports");
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingDatabases, setIsLoadingDatabases] = useState(true);
  const [importPath, setImportPath] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [managementView, setManagementView] = useState<ManagementView>("queue");
  const [libraryView, setLibraryView] = useState<LibraryView>("videos");
  const [isControllingTask, setIsControllingTask] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [ownerRef, setOwnerRef] = useState("");
  const [isArchivingSpace, setIsArchivingSpace] = useState(false);
  const [isSubmittingSpace, setIsSubmittingSpace] = useState(false);
  const [exportingKey, setExportingKey] = useState("");
  const [deletingKey, setDeletingKey] = useState("");
  const [exportTarget, setExportTarget] = useState<ExportTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [duplicateVideo, setDuplicateVideo] = useState<VideoSummary | null>(null);
  const [pendingParseTarget, setPendingParseTarget] = useState("");
  const [hiddenTaskKeys, setHiddenTaskKeys] = useState<Set<string>>(() => new Set());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const parseProgress = useProgressPolling(isParsing, "parse");
  const spaceProgress = useProgressPolling(true);
  const [parseDelay, setParseDelay] = useState(() => {
    const saved = window.localStorage.getItem("bilibili-comment-delay");
    return saved ? Number(saved) || 0.35 : 0.35;
  });
  const spaceQueue = spaceProgress?.queue;
  const taskQueue = useMemo(() => mergeProgressIntoQueue(spaceQueue, spaceProgress, hiddenTaskKeys), [hiddenTaskKeys, spaceQueue, spaceProgress]);
  const hasSpaceQueueWork = Boolean(spaceQueue?.active || spaceQueue?.queued?.length);
  const hasTaskWork = Boolean(taskQueue.active || taskQueue.queued.length || taskQueue.recent.length);
  const isTaskBusy = isParsing || hasSpaceQueueWork;
  const activeDatabase = useMemo(
    () => databases.find((database) => database.id === activeDbId) || databases.find((database) => database.id === "main"),
    [activeDbId, databases],
  );

  const loadDatabases = useCallback(
    async (options?: { quiet?: boolean; selectId?: string }) => {
      const selectedId = options?.selectId || activeDbId;
      if (!options?.quiet) {
        setIsLoadingDatabases(true);
      }
      try {
        const payload = await fetchDatabases(selectedId);
        setDatabases(payload.databases);
        setHotplugDir(payload.hotplug_dir);
        setLegacyExportDir(payload.legacy_export_dir);
        if (!payload.databases.some((database) => database.id === selectedId)) {
          setActiveDbId("main");
          window.localStorage.setItem("bilibili-active-db-id", "main");
          window.history.replaceState({}, "", "/");
          setMessage("所选数据库已不存在，已切回主数据库");
        }
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setIsLoadingDatabases(false);
      }
    },
    [activeDbId],
  );

  const loadVideos = useCallback(async (options?: { append?: boolean; offset?: number; quiet?: boolean }) => {
    if (!options?.quiet) {
      setIsLoading(true);
    }
    setError("");
    try {
      const offset = options?.offset || 0;
      const payload = await fetchVideos(activeDbId, { limit: VIDEO_PAGE_SIZE, offset });
      setVideos((current) => (options?.append ? mergeVideosByBvid(current, payload.videos) : payload.videos));
      setOwnerSummaries(payload.owners || []);
      setVideoTotal(payload.total ?? payload.videos.length);
      setHasMoreVideos(Boolean(payload.has_more));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsLoading(false);
    }
  }, [activeDbId]);

  useEffect(() => {
    void loadDatabases();
  }, [loadDatabases]);

  useEffect(() => {
    fetchCookieStatus()
      .then(setCookieStatus)
      .catch(() => setCookieStatus(null));
  }, []);

  useEffect(() => {
    setOwnerFilter("all");
    setDuplicateVideo(null);
    setPendingParseTarget("");
    void loadVideos();
  }, [activeDbId, loadVideos]);

  useEffect(() => {
    if (!isArchivingSpace || hasSpaceQueueWork) return;
    setIsArchivingSpace(false);
    void loadVideos();
    void loadDatabases({ quiet: true });
  }, [hasSpaceQueueWork, isArchivingSpace, loadDatabases, loadVideos]);

  useEffect(() => {
    if (!hasSpaceQueueWork) return;
    setManagementView("queue");
    const timer = window.setInterval(() => {
      void loadVideos({ quiet: true });
      void loadDatabases({ quiet: true });
    }, 15000);
    return () => window.clearInterval(timer);
  }, [hasSpaceQueueWork, loadDatabases, loadVideos]);

  const ownerGroups = useMemo(() => {
    if (ownerSummaries.length) {
      return ownerSummaries.map((owner) => ({
        bvids: owner.owner_mid ? [] : videos.filter((video) => ownerKey(video) === owner.key).map((video) => video.bvid),
        key: owner.key,
        name: owner.name,
        ownerMid: owner.owner_mid,
        videoCount: owner.video_count,
        commentCount: owner.comment_count,
        danmakuCount: owner.danmaku_count,
        storageBytes: owner.storage_bytes,
      }));
    }

    const groups = new Map<string, OwnerGroup>();
    for (const video of videos) {
      const key = ownerKey(video);
      const existing = groups.get(key);
      if (existing) {
        existing.bvids.push(video.bvid);
        existing.videoCount += 1;
        existing.commentCount += video.comment_total_count || 0;
        existing.danmakuCount += video.danmaku_count || 0;
        existing.storageBytes = estimateOwnerStorageBytes(existing.commentCount, existing.danmakuCount, existing.videoCount);
      } else {
        groups.set(key, {
          bvids: [video.bvid],
          key,
          name: ownerName(video),
          ownerMid: (video.owner_mid || "").trim(),
          videoCount: 1,
          commentCount: video.comment_total_count || 0,
          danmakuCount: video.danmaku_count || 0,
          storageBytes: estimateOwnerStorageBytes(video.comment_total_count || 0, video.danmaku_count || 0, 1),
        });
      }
    }

    return Array.from(groups.values()).sort((first, second) => {
      if (second.videoCount !== first.videoCount) return second.videoCount - first.videoCount;
      if (second.commentCount !== first.commentCount) return second.commentCount - first.commentCount;
      return first.name.localeCompare(second.name, "zh-Hans-CN");
    });
  }, [ownerSummaries, videos]);

  useEffect(() => {
    if (ownerFilter === "all") return;
    if (!ownerGroups.some((group) => group.key === ownerFilter)) {
      setOwnerFilter("all");
    }
  }, [ownerFilter, ownerGroups]);

  const selectedOwner = ownerGroups.find((group) => group.key === ownerFilter);
  const selectedOwnerName = selectedOwner?.name;

  const filteredVideos = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const ownerScopedVideos =
      ownerFilter === "all" ? videos : videos.filter((video) => ownerKey(video) === ownerFilter);
    if (!needle) return ownerScopedVideos;
    return ownerScopedVideos.filter((video) => {
      return (
        video.title.toLowerCase().includes(needle) ||
        video.bvid.toLowerCase().includes(needle) ||
        (video.owner_name || "").toLowerCase().includes(needle)
      );
    });
  }, [ownerFilter, query, videos]);

  const totals = useMemo(() => {
    return videos.reduce(
      (acc, video) => {
        acc.views += video.stat_view || 0;
        acc.comments += video.comment_total_count || 0;
        acc.active += video.active_comment_count || 0;
        acc.deleted += video.deleted_comment_count || 0;
        acc.likes += video.comment_like_count || 0;
        acc.danmaku += video.danmaku_count || 0;
        return acc;
      },
      { views: 0, comments: 0, active: 0, deleted: 0, likes: 0, danmaku: 0 },
    );
  }, [videos]);

  async function loadMoreVideos() {
    await loadVideos({ append: true, offset: videos.length, quiet: true });
  }

  async function submitParse(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = url.trim();
    if (!target) {
      logClientEvent("client.user.parse.invalid_input", "parse submitted without video reference");
      setError("请输入 Bilibili 视频链接或 BV 号");
      return;
    }

    const bvid = extractBvid(target);
    const existingVideo = bvid ? videos.find((video) => video.bvid.toLowerCase() === bvid.toLowerCase()) : undefined;
    if (existingVideo) {
      logClientEvent("client.user.parse.duplicate_detected", "existing video detected before parse", {
        bvid: existingVideo.bvid,
        title: existingVideo.title,
      });
      setDuplicateVideo(existingVideo);
      setPendingParseTarget(target);
      setError("");
      setMessage("");
      return;
    }

    await runParse(target);
  }

  function exportSuccessNotice(
    payload: { directory_path?: string; format: string; relative_path: string },
    title: string,
  ): NoticeState {
    const isJson = payload.format === "json";
    const directory = payload.directory_path;
    return {
      kind: "success",
      title,
      message: isJson
        ? `${payload.relative_path} 已导出为 JSON 数据文件，可再次导入`
        : `${payload.relative_path} 已导出为独立数据库，可在数据库页面切换查看`,
      actionLabel: "打开所在文件夹",
      onAction: directory ? () => void openExportDirectory(directory) : undefined,
    };
  }

  async function openExportDirectory(path: string) {
    try {
      await openLocalPath(path);
      logClientEvent("client.user.export.open_folder", "opened export folder", { path });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setNotice({ kind: "error", title: "打开文件夹失败", message: text });
    }
  }

  function videoExportLabel(video: VideoSummary) {
    return video.title || "未命名视频";
  }

  function batchExportLabel(prefix: string, names: string[], count: number) {
    const readable = names.slice(0, 2).filter(Boolean).join("_");
    const suffix = names.length > 2 ? `_等${names.length}项` : "";
    return `${prefix}_${readable || `${count}项`}${suffix}`;
  }

  async function exportOwnerDatabase(owner = selectedOwner, format: ExportFormat) {
    if (!owner || (!owner.ownerMid && !owner.bvids.length)) {
      setNotice({ kind: "error", title: "UP 主导出失败", message: "这个 UP 主缺少 mid，且当前未加载到可导出的视频列表。" });
      return;
    }
    setExportingKey(`owner:${owner.key}`);
    setExportTarget(null);
    setError("");
    setMessage(`正在导出 ${owner.name} 的 UP 主${format === "json" ? " JSON 文件" : "独立数据库"}`);
    try {
      const payload = await exportDatabaseArchive({
        bvids: owner.ownerMid ? undefined : owner.bvids,
        db_id: activeDbId,
        format,
        label: owner.name || owner.ownerMid || "未命名UP主",
        owner_mid: owner.ownerMid || undefined,
      });
      setMessage(
        `导出完成：${payload.relative_path}，${payload.video_count} 个视频，${formatBytes(payload.size_bytes)}`,
      );
      setNotice(exportSuccessNotice(payload, format === "json" ? "UP 主 JSON 导出完成" : "UP 主数据库导出完成"));
      await loadDatabases({ quiet: true, selectId: payload.database?.id || activeDbId });
      logClientEvent("client.user.database_export.owner_success", "owner database exported", {
        db_id: activeDbId,
        owner: owner.name,
        owner_mid: owner.ownerMid,
        video_count: payload.video_count,
        size_bytes: payload.size_bytes,
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setNotice({ kind: "error", title: "UP 主数据库导出失败", message: text });
      logClientEvent("client.user.database_export.owner_error", text, {
        owner: owner.name,
        owner_mid: owner.ownerMid,
        video_count: owner.videoCount,
      });
    } finally {
      setExportingKey("");
    }
  }

  async function exportVideoDatabase(video: VideoSummary, format: ExportFormat) {
    setExportingKey(`video:${video.bvid}`);
    setExportTarget(null);
    setError("");
    setMessage(`正在导出 ${video.bvid} 的${format === "json" ? " JSON 文件" : "独立数据库"}`);
    try {
      const payload = await exportDatabaseArchive({
        bvid: video.bvid,
        db_id: activeDbId,
        format,
        label: videoExportLabel(video),
      });
      setMessage(`导出完成：${payload.relative_path}，${formatBytes(payload.size_bytes)}`);
      setNotice(exportSuccessNotice(payload, format === "json" ? "视频 JSON 导出完成" : "视频数据库导出完成"));
      await loadDatabases({ quiet: true, selectId: payload.database?.id || activeDbId });
      logClientEvent("client.user.database_export.video_success", "video database exported", {
        db_id: activeDbId,
        bvid: video.bvid,
        size_bytes: payload.size_bytes,
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setNotice({ kind: "error", title: "视频数据库导出失败", message: text });
      logClientEvent("client.user.database_export.video_error", text, {
        bvid: video.bvid,
      });
    } finally {
      setExportingKey("");
    }
  }

  async function exportBatchVideos(selectedVideos: VideoSummary[], format: ExportFormat) {
    const bvids = selectedVideos.map((video) => video.bvid);
    if (!bvids.length) return;
    setExportingKey("batch:videos");
    setError("");
    setMessage(`正在导出 ${bvids.length} 个视频`);
    try {
      const payload = await exportDatabaseArchive({
        bvids,
        db_id: activeDbId,
        format,
        label: batchExportLabel("批量视频", selectedVideos.map((video) => video.title || video.bvid), bvids.length),
      });
      setMessage(`导出完成：${payload.relative_path}，${formatBytes(payload.size_bytes)}`);
      setNotice(exportSuccessNotice(payload, format === "json" ? "批量视频 JSON 导出完成" : "批量视频数据库导出完成"));
      await loadDatabases({ quiet: true, selectId: payload.database?.id || activeDbId });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setNotice({ kind: "error", title: "批量导出失败", message: text });
    } finally {
      setExportingKey("");
    }
  }

  async function exportBatchOwners(owners: OwnerGroup[], format: ExportFormat) {
    if (!owners.length) return;
    if (owners.length === 1 && owners[0].ownerMid) {
      await exportOwnerDatabase(owners[0], format);
      return;
    }
    if (owners.some((owner) => owner.ownerMid)) {
      setNotice({
        kind: "warning",
        title: "批量 UP 导出需要逐个执行",
        message: "带 mid 的 UP 主可以完整导出，但多个 UP 合并导出需要展开为视频列表。请一次导出一个 UP，或先加载更多视频后再合并导出。",
      });
      return;
    }
    const bvids = Array.from(new Set(owners.flatMap((owner) => owner.bvids)));
    if (!bvids.length || bvids.length < owners.reduce((sum, owner) => sum + owner.videoCount, 0)) {
      setNotice({ kind: "warning", title: "批量导出需要完整视频列表", message: "多个 UP 合并导出依赖已加载的视频；请先加载更多视频，或一次导出一个 UP。" });
      return;
    }
    setExportingKey("batch:owners");
    setError("");
    setMessage(`正在导出 ${owners.length} 个 UP`);
    try {
      const payload = await exportDatabaseArchive({
        bvids,
        db_id: activeDbId,
        format,
        label: batchExportLabel("批量UP", owners.map((owner) => owner.name || owner.ownerMid), owners.length),
      });
      setMessage(`导出完成：${payload.relative_path}，${formatBytes(payload.size_bytes)}`);
      setNotice(exportSuccessNotice(payload, format === "json" ? "批量 UP JSON 导出完成" : "批量 UP 数据库导出完成"));
      await loadDatabases({ quiet: true, selectId: payload.database?.id || activeDbId });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setNotice({ kind: "error", title: "批量导出失败", message: text });
    } finally {
      setExportingKey("");
    }
  }

  function queueBatchVideoDelete(selectedVideos: VideoSummary[]) {
    if (!selectedVideos.length) return;
    setDeleteTarget({ kind: "videos", videos: selectedVideos });
  }

  function queueBatchOwnerDelete(owners: OwnerGroup[]) {
    if (!owners.length) return;
    if (owners.length > 1 && owners.some((owner) => owner.ownerMid)) {
      setNotice({
        kind: "warning",
        title: "批量删除请逐个 UP 执行",
        message: "为避免误删过大范围的数据，带 mid 的 UP 主请一次删除一个；不需要先加载完整视频列表。",
      });
      return;
    }
    if (owners.length > 1 && owners.some((owner) => owner.bvids.length < owner.videoCount)) {
      setNotice({ kind: "warning", title: "批量删除需要完整视频列表", message: "多个 UP 同时删除依赖已加载的视频列表；请先加载更多视频，或一次删除一个 UP。" });
      return;
    }
    setDeleteTarget({ kind: "owners", owners });
  }

  function deletePayloadForTarget(target: DeleteTarget): { owner_mid?: string; bvid?: string; bvids?: string[] } {
    if (target.kind === "owner") return { owner_mid: target.owner.ownerMid };
    if (target.kind === "video") return { bvid: target.video.bvid };
    if (target.kind === "videos") return { bvids: target.videos.map((video) => video.bvid) };
    const mids = target.owners.map((owner) => owner.ownerMid).filter(Boolean);
    if (mids.length === 1 && target.owners.length === 1) return { owner_mid: mids[0] };
    return { bvids: Array.from(new Set(target.owners.flatMap((owner) => owner.bvids))) };
  }

  function deleteTargetVideoCount(target: DeleteTarget) {
    if (target.kind === "owner") return target.owner.videoCount;
    if (target.kind === "owners") return target.owners.reduce((sum, owner) => sum + owner.videoCount, 0);
    if (target.kind === "videos") return target.videos.length;
    return 1;
  }

  async function queueArchiveDeleteTarget() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    const payloadTarget = deletePayloadForTarget(target);
    const removedBvids = new Set(payloadTarget.bvids || []);
    setDeletingKey(`delete:${target.kind}`);
    setError("");
    setMessage("");
    try {
      const payload = await deleteArchiveData({ db_id: activeDbId, ...payloadTarget });
      setDeleteTarget(null);
      setOwnerFilter("all");
      setLibraryView("tasks");
      setManagementView("queue");
      if (payloadTarget.owner_mid) {
        setVideos((current) => current.filter((video) => video.owner_mid !== payloadTarget.owner_mid));
        setOwnerSummaries((current) => current.filter((owner) => owner.owner_mid !== payloadTarget.owner_mid));
      } else {
        setVideos((current) => current.filter((video) => !removedBvids.has(video.bvid)));
      }
      setVideoTotal((current) => Math.max(0, current - deleteTargetVideoCount(target)));
      setMessage(payload.message || `删除任务已加入队列：${payload.task_id || "等待执行"}`);
      setNotice({
        kind: "success",
        title: "删除任务已提交",
        message: "本地档案会在后台删除，任务列表会显示进度；完成后数据库空间也会在后台整理。",
      });
      window.setTimeout(() => {
        void loadVideos({ quiet: true });
        void loadDatabases({ quiet: true, selectId: activeDbId });
      }, 8000);
      logClientEvent("client.user.archive_delete.success", "archive delete task queued", {
        db_id: activeDbId,
        target: target.kind,
        task_id: payload.task_id,
        queue_position: payload.queue_position,
        queued_videos: deleteTargetVideoCount(target),
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setNotice({ kind: "error", title: "删除失败", message: text });
      logClientEvent("client.user.archive_delete.error", text, {
        db_id: activeDbId,
        target: target.kind,
      });
    } finally {
      setDeletingKey("");
    }
  }

  async function runParse(target: string) {
    const targetBvid = extractBvid(target);
    logClientEvent("client.user.parse.start", "user started video parse", {
      bvid: targetBvid,
      db_id: activeDbId,
      delay: parseDelay,
      source: duplicateVideo ? "duplicate_confirm" : "form",
    });
    setLibraryView("tasks");
    setIsParsing(true);
    setDuplicateVideo(null);
    setPendingParseTarget("");
    setError("");
    setMessage("正在提交视频抓取任务，任务列表会显示当前进度");
    try {
      window.localStorage.setItem("bilibili-comment-delay", String(parseDelay));
      const payload = await parseVideo(target, parseDelay, activeDbId);
      setHiddenTaskKeys((previous) => {
        const next = new Set(previous);
        next.delete(`id:parse:${payload.bvid}`);
        return next;
      });
      logClientEvent("client.user.parse.success", "video parse task queued", {
        db_id: activeDbId,
        bvid: payload.bvid,
        task_id: payload.task_id,
        queue_position: payload.queue_position,
        scraped_count: payload.scraped_count || 0,
        after_count: payload.after_count || 0,
        danmaku_count: payload.danmaku_count || 0,
      });
      setMessage(payload.message || `视频抓取任务已加入队列：${payload.bvid}`);
    } catch (reason: unknown) {
      logClientEvent("client.user.parse.error", reason instanceof Error ? reason.message : String(reason), {
        db_id: activeDbId,
        bvid: targetBvid,
      });
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsParsing(false);
    }
  }

  async function submitSpaceArchive(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = ownerRef.trim();
    if (!target) {
      logClientEvent("client.user.space_archive.invalid_input", "space archive submitted without owner reference");
      setError("请输入 UP 主主页链接或 mid");
      return;
    }

    logClientEvent("client.user.space_archive.start", "user started space archive", {
      db_id: activeDbId,
      owner_ref: summarizeOwnerRef(target),
      delay: parseDelay,
    });
    setIsArchivingSpace(true);
    setIsSubmittingSpace(true);
    setError("");
    setMessage("UP 主全部视频归档已加入队列，首页会显示当前进度");
    try {
      const payload = await archiveSpaceVideos(target, {
        delay: parseDelay,
        dbId: activeDbId,
      });
      setOwnerRef(payload.mid);
      setLibraryView("tasks");
      setMessage(`已加入抓取队列：${payload.mid}，排队第 ${payload.queue_position} 个`);
      logClientEvent("client.user.space_archive.accepted", "space archive task accepted", {
        db_id: activeDbId,
        mid: payload.mid,
        task_id: payload.task_id,
        queue_position: payload.queue_position,
      });
    } catch (reason: unknown) {
      logClientEvent("client.user.space_archive.error", reason instanceof Error ? reason.message : String(reason), {
        owner_ref: summarizeOwnerRef(target),
      });
      setIsArchivingSpace(false);
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("");
    } finally {
      setIsSubmittingSpace(false);
    }
  }

  async function controlTasks(action: TaskControlAction, taskId?: string) {
    setIsControllingTask(true);
    setError("");
    try {
      await controlSpaceTasks(action, taskId);
      if (action === "clear") {
        rememberHiddenTasks(taskId);
      }
      const actionLabel = taskActionLabel(action);
      setMessage(taskId ? `任务已请求${actionLabel}` : `全部任务已请求${actionLabel}`);
      logClientEvent("client.user.space_task.control", "space task control requested", {
        action,
        task_id: taskId,
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      logClientEvent("client.user.space_task.control_error", text, { action, task_id: taskId });
    } finally {
      setIsControllingTask(false);
    }
  }

  function rememberHiddenTasks(taskId?: string) {
    const targets = taskId ? allQueueTasks(taskQueue).filter((task) => task.id === taskId) : taskQueue.recent;
    if (!targets.length && taskId) {
      targets.push({ id: taskId } as ProgressTask);
    }
    setHiddenTaskKeys((previous) => {
      const next = new Set(previous);
      for (const task of targets) {
        for (const key of taskHideKeys(task)) {
          next.add(key);
        }
      }
      return next;
    });
  }

  function openVideo(video: VideoSummary) {
    logClientEvent("client.user.video.open_existing", "opened existing local archive", {
      db_id: activeDbId,
      bvid: video.bvid,
      title: video.title,
    });
    window.history.pushState({}, "", dbPath(`/video/${video.bvid}`, activeDbId));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  async function refreshDatabaseCatalog() {
    logClientEvent("client.user.databases.refresh", "user refreshed database catalog", {
      db_id: activeDbId,
    });
    setError("");
    await loadDatabases({ selectId: activeDbId });
    await loadVideos({ quiet: true });
  }

  async function submitDatabaseImport(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = importPath.trim();
    if (!target) {
      setError("请输入要导入的 SQLite 数据库或 JSON 数据文件路径");
      return;
    }
    setIsImporting(true);
    setError("");
    setMessage("正在导入数据库");
    try {
      const payload = await importDatabase(target);
      setImportPath("");
      setActiveDatabase(payload.database.id, false);
      await loadDatabases({ quiet: true, selectId: payload.database.id });
      setMessage(
        `导入完成：${payload.database.relative_path}，已切换到该数据库，${payload.database.video_count} 个视频，${formatBytes(
          payload.database.size_bytes,
        )}`,
      );
      setNotice({
        kind: "success",
        title: "数据库导入完成",
        message: `${payload.database.relative_path} 已导入并切换，包含 ${payload.database.video_count} 个视频`,
      });
      logClientEvent("client.user.databases.import_success", "database imported", {
        db_id: payload.database.id,
        file_name: payload.database.file_name,
        video_count: payload.database.video_count,
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setMessage("");
      setNotice({ kind: "error", title: "数据库导入失败", message: text });
      logClientEvent("client.user.databases.import_error", text);
    } finally {
      setIsImporting(false);
    }
  }

  async function importSelectedFiles(fileList: FileList | null, source: "file" | "folder") {
    const selectedFiles = Array.from(fileList || []).filter((file) => /\.(db|sqlite|sqlite3|json)$/i.test(file.name));
    if (!selectedFiles.length) {
      setNotice({ kind: "error", title: "未选择导入文件", message: "请选择 .db / .sqlite / .sqlite3 或 .json 文件" });
      return;
    }
    setIsImporting(true);
    setError("");
    setMessage(`正在导入 ${selectedFiles.length} 个数据库或 JSON 文件`);
    try {
      const payload = await importDatabaseFiles(selectedFiles);
      const database = payload.database;
      setActiveDatabase(database.id, false);
      await loadDatabases({ quiet: true, selectId: database.id });
      setMessage(`导入完成：${payload.imported_count || selectedFiles.length} 个文件，已切换到 ${database.name}`);
      setNotice({
        kind: payload.errors?.length ? "warning" : "success",
        title: payload.errors?.length ? "部分数据库导入完成" : "数据库导入完成",
        message: [
          `成功导入 ${payload.imported_count || payload.databases?.length || 1} 个数据库文件`,
          payload.errors?.length ? `失败 ${payload.errors.length} 个：${payload.errors.slice(0, 3).join("；")}` : "",
        ]
          .filter(Boolean)
          .join("。"),
      });
      logClientEvent("client.user.databases.import_file_success", "database files imported", {
        db_id: database.id,
        file_count: selectedFiles.length,
        source,
      });
    } catch (reason: unknown) {
      const text = reason instanceof Error ? reason.message : String(reason);
      setError(text);
      setMessage("");
      setNotice({ kind: "error", title: "数据库文件导入失败", message: text });
      logClientEvent("client.user.databases.import_file_error", text, { file_count: selectedFiles.length, source });
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  }

  function setActiveDatabase(dbId: string, reload = true) {
    setActiveDbId(dbId);
    window.localStorage.setItem("bilibili-active-db-id", dbId);
    const path = dbId === "main" ? "/" : `/?db_id=${encodeURIComponent(dbId)}`;
    window.history.replaceState({}, "", path);
    if (reload) {
      logClientEvent("client.user.databases.select", "user selected database", { db_id: dbId });
      setMessage("");
      setError("");
    }
  }

  return (
    <main className="app-shell">
      <LibraryHeader
        activeDatabase={activeDatabase}
        commentCount={totals.comments}
        isLoading={isLoading}
        isLoadingDatabases={isLoadingDatabases}
        showSettings={showSettings}
        videoCount={videoTotal || videos.length}
        onRefresh={() => {
          logClientEvent("client.user.videos.refresh_click", "user refreshed video list", {
            db_id: activeDbId,
            video_count: videos.length,
          });
          void refreshDatabaseCatalog();
        }}
        onToggleSettings={() => {
          logClientEvent("client.user.settings.toggle", "user toggled parse settings", {
            show_settings: !showSettings,
          });
          setShowSettings((value) => !value);
        }}
      />

      <StatusStrips
        error={error}
        hasSpaceQueueWork={hasSpaceQueueWork}
        isParsing={isParsing}
        message={message}
        parseProgress={parseProgress}
        spaceProgress={spaceProgress}
      />

      <LibraryStats totals={totals} videoCount={videoTotal || videos.length} />

      <LibraryTabs
        active={libraryView}
        databaseCount={databases.length}
        hasTaskWork={hasTaskWork}
        manageCount={ownerGroups.length + (videoTotal || videos.length)}
        queuedCount={(taskQueue.active ? 1 : 0) + taskQueue.queued.length}
        videoCount={videoTotal || videos.length}
        onChange={setLibraryView}
      />

      {libraryView === "videos" && (
        <section className="mx-auto grid max-w-[1540px] gap-4 px-4 pb-6 lg:grid-cols-[420px_minmax(0,1fr)] lg:px-6">
          <LibrarySidebar
            activeDatabase={activeDatabase}
            cookieStatus={cookieStatus}
            duplicateVideo={duplicateVideo}
            hasSpaceQueueWork={hasSpaceQueueWork}
            hotplugDir={hotplugDir}
            isParsing={isParsing}
            isSubmittingSpace={isSubmittingSpace}
            isTaskBusy={isTaskBusy}
            ownerFilter={ownerFilter}
            ownerGroups={ownerGroups}
            ownerRef={ownerRef}
            parseDelay={parseDelay}
            showSettings={showSettings}
            totals={totals}
            url={url}
            videoCount={videos.length}
            onDuplicateOpen={openVideo}
            onDuplicateReparse={() => {
              if (!duplicateVideo) return;
              logClientEvent("client.user.parse.duplicate_confirm", "user confirmed reparsing existing video", {
                bvid: duplicateVideo.bvid,
              });
              void runParse(pendingParseTarget);
            }}
            onOwnerExport={(owner, format) => void exportOwnerDatabase(owner, format)}
            onOwnerFilterChange={(key, owner) => {
              logClientEvent("client.user.videos.owner_filter", "user selected owner filter", {
                owner: owner?.name || "all",
                video_count: owner?.videoCount,
              });
              setOwnerFilter(key);
            }}
            onOwnerRefChange={setOwnerRef}
            onParseDelayChange={setParseDelay}
            onSubmitParse={submitParse}
            onSubmitSpaceArchive={submitSpaceArchive}
            onUrlChange={(value) => {
              setUrl(value);
              setDuplicateVideo(null);
              setPendingParseTarget("");
            }}
          />

          <VideoListPanel
            activeDbId={activeDbId}
            isLoading={isLoading}
            query={query}
            selectedOwnerName={selectedOwnerName}
            totalVideoCount={videos.length}
            backendTotalVideoCount={videoTotal}
            hasMore={hasMoreVideos}
            videos={filteredVideos}
            onLoadMore={() => void loadMoreVideos()}
            onQueryChange={setQuery}
          />
        </section>
      )}

      {libraryView === "manage" && (
        <BatchManagementPanel
          backendTotalVideoCount={videoTotal}
          disabled={Boolean(exportingKey || deletingKey)}
          hasMoreVideos={hasMoreVideos}
          isLoadingVideos={isLoading}
          ownerGroups={ownerGroups}
          videos={videos}
          onDeleteOwners={queueBatchOwnerDelete}
          onDeleteVideos={queueBatchVideoDelete}
          onExportOwners={(owners, format) => void exportBatchOwners(owners, format)}
          onExportVideos={(selectedVideos, format) => void exportBatchVideos(selectedVideos, format)}
          onLoadMoreVideos={() => void loadMoreVideos()}
        />
      )}

      {libraryView === "tasks" && (
        <TaskManagementPanel isControlling={isControllingTask} queue={taskQueue} onControl={(action, taskId) => void controlTasks(action, taskId)} />
      )}

      {libraryView === "databases" && (
        <section className="mx-auto max-w-[1540px] px-4 pb-4 lg:px-6">
          <ManagementPanel
            activeDbId={activeDbId}
            cookieStatus={cookieStatus}
            databases={databases}
            hotplugDir={hotplugDir}
            importPath={importPath}
            isImporting={isImporting}
            isLoading={isLoadingDatabases}
            legacyExportDir={legacyExportDir}
            queue={spaceQueue}
            view={managementView === "queue" ? "database" : managementView}
            onCookieStatusChange={setCookieStatus}
            onImportPathChange={setImportPath}
            onPickFiles={() => fileInputRef.current?.click()}
            onPickFolder={() => folderInputRef.current?.click()}
            onRefresh={() => void refreshDatabaseCatalog()}
            onSelect={setActiveDatabase}
            onSubmitImport={submitDatabaseImport}
            onViewChange={setManagementView}
          />
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept=".db,.sqlite,.sqlite3,.json"
            multiple
            onChange={(event) => void importSelectedFiles(event.target.files, "file")}
          />
          <input
            ref={folderInputRef}
            className="hidden"
            type="file"
            accept=".db,.sqlite,.sqlite3,.json"
            multiple
            // @ts-expect-error Chromium supports folder selection via webkitdirectory.
            webkitdirectory="true"
            onChange={(event) => void importSelectedFiles(event.target.files, "folder")}
          />
        </section>
      )}

      {libraryView === "auth" && (
        <section className="mx-auto max-w-[1540px] px-4 pb-4 lg:px-6">
          <AuthPanel cookieStatus={cookieStatus} onStatusChange={setCookieStatus} />
        </section>
      )}
      {exportTarget && (
        <ExportChoiceDialog
          target={exportTarget}
          onClose={() => setExportTarget(null)}
          onChoose={(format) => {
            if (exportTarget.kind === "owner") {
              void exportOwnerDatabase(exportTarget.owner, format);
            } else {
              void exportVideoDatabase(exportTarget.video, format);
            }
          }}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmDialog
          disabled={Boolean(deletingKey)}
          target={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => void queueArchiveDeleteTarget()}
        />
      )}
      {notice && <NoticeDialog notice={notice} onClose={() => setNotice(null)} />}
    </main>
  );
}

export function mergeProgressIntoQueue(queue: ProgressQueue | undefined, progress: ProgressState | null, hiddenTaskKeys: Set<string> = new Set()): ProgressQueue {
  const base: ProgressQueue = {
    active: queue?.active || null,
    queued: queue?.queued || [],
    recent: (queue?.recent || []).filter((task) => !isHiddenTask(task, hiddenTaskKeys)),
  };
  const progressTask = progressToTask(progress);
  if (!progressTask) return base;
  if (isHiddenTask(progressTask, hiddenTaskKeys)) return base;
  if (queueHasMatchingTask(base, progressTask)) return base;

  if (progressTask.status === "running" || progressTask.status === "waiting") {
    return {
      ...base,
      active: progressTask,
    };
  }

  const alreadyInRecent = base.recent.some((task) => task.id === progressTask.id);
  return {
    ...base,
    recent: alreadyInRecent ? base.recent : [progressTask, ...base.recent],
  };
}

function allQueueTasks(queue: ProgressQueue) {
  return [queue.active, ...queue.queued, ...queue.recent].filter(Boolean) as ProgressTask[];
}

function isHiddenTask(task: ProgressTask, hiddenTaskKeys: Set<string>) {
  return taskHideKeys(task).some((key) => hiddenTaskKeys.has(key));
}

function taskHideKeys(task: ProgressTask) {
  const keys = [`id:${task.id}`];
  const bvid = task.bvid || task.current_bvid;
  if (bvid && ["parse", "comments", "danmaku"].includes(task.kind)) {
    keys.push(`id:${task.kind}:${bvid}`);
  }
  return keys;
}

function queueHasMatchingTask(queue: ProgressQueue, task: ProgressTask) {
  return [queue.active, ...queue.queued, ...queue.recent].some((existing) => {
    if (!existing) return false;
    if (existing.id === task.id) return true;
    const existingBvid = existing.bvid || existing.current_bvid;
    const taskBvid = task.bvid || task.current_bvid;
    return Boolean(existingBvid && taskBvid && existing.kind === task.kind && existingBvid === taskBvid);
  });
}

function taskActionLabel(action: TaskControlAction) {
  if (action === "pause") return "暂停";
  if (action === "resume") return "继续";
  if (action === "stop") return "停止";
  if (action === "retry") return "重试";
  return "清除";
}

function progressToTask(progress: ProgressState | null): ProgressTask | null {
  if (!progress || !["parse", "comments", "danmaku"].includes(progress.kind)) return null;
  const bvid = progress.bvid || "";
  const taskKindLabel = progress.kind === "parse" ? "视频抓取" : progress.kind === "comments" ? "评论刷新" : "弹幕刷新";
  const status = progress.active ? "running" : progress.error ? "failed" : progress.done ? "finished" : "queued";
  return {
    id: `${progress.kind}:${bvid || progress.started_at || "latest"}`,
    kind: progress.kind,
    mid: "",
    owner_ref: taskKindLabel,
    status,
    message: progress.message || taskKindLabel,
    created_at: progress.started_at,
    updated_at: progress.updated_at,
    started_at: progress.started_at,
    finished_at: progress.done ? progress.updated_at : "",
    progress: progress.percent || 0,
    current_bvid: bvid,
    total: 1,
    complete: progress.done && !progress.error ? 1 : 0,
    archived: progress.done && !progress.error ? 1 : 0,
    skipped: 0,
    failed: progress.error ? 1 : 0,
  };
}

function mergeVideosByBvid(current: VideoSummary[], incoming: VideoSummary[]) {
  const byBvid = new Map(current.map((video) => [video.bvid, video]));
  for (const video of incoming) {
    byBvid.set(video.bvid, video);
  }
  return Array.from(byBvid.values());
}

function estimateOwnerStorageBytes(commentCount: number, danmakuCount: number, videoCount: number) {
  return commentCount * 900 + danmakuCount * 260 + videoCount * 4096;
}
