import {
  AlertTriangle,
  Database,
  Eye,
  Heart,
  LinkIcon,
  ListTree,
  MessageCircle,
  FolderOpen,
  PlayCircle,
  PlusCircle,
  RefreshCcw,
  Search,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import {
  archiveSpaceVideos,
  exportDatabaseArchive,
  fetchDatabases,
  fetchVideos,
  importDatabase,
  importDatabaseFiles,
  logClientEvent,
  parseVideo,
} from "../api/client";
import { ProgressBanner } from "../components/common";
import { InfoRow } from "../components/common";
import { StatTile } from "../components/ui/StatTile";
import { ExportChoiceDialog } from "../components/video-library/ExportChoiceDialog";
import { ManagementPanel } from "../components/video-library/ManagementPanel";
import { NoticeDialog } from "../components/video-library/NoticeDialog";
import { OwnerFilterButton } from "../components/video-library/OwnerFilterButton";
import type { ExportFormat, ExportTarget, ManagementView, NoticeState, OwnerGroup } from "../components/video-library/types";
import { VideoCard } from "../components/video-library/VideoCard";
import { useProgressPolling } from "../hooks/useProgressPolling";
import { cn, formatNumber } from "../lib/utils";
import { dbPath, extractBvid, formatBytes, initialDatabaseId, ownerKey, ownerName, summarizeOwnerRef } from "../lib/videoLibrary";
import type { DatabaseInfo, VideoSummary } from "../types";

export function VideoLibraryPage() {
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [databases, setDatabases] = useState<DatabaseInfo[]>([]);
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
  const [isParsing, setIsParsing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [ownerRef, setOwnerRef] = useState("");
  const [isArchivingSpace, setIsArchivingSpace] = useState(false);
  const [isSubmittingSpace, setIsSubmittingSpace] = useState(false);
  const [exportingKey, setExportingKey] = useState("");
  const [exportTarget, setExportTarget] = useState<ExportTarget | null>(null);
  const [duplicateVideo, setDuplicateVideo] = useState<VideoSummary | null>(null);
  const [pendingParseTarget, setPendingParseTarget] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const parseProgress = useProgressPolling(isParsing, "parse");
  const spaceProgress = useProgressPolling(true);
  const [parseDelay, setParseDelay] = useState(() => {
    const saved = window.localStorage.getItem("bilibili-comment-delay");
    return saved ? Number(saved) || 0.35 : 0.35;
  });
  const spaceQueue = spaceProgress?.queue;
  const hasSpaceQueueWork = Boolean(spaceQueue?.active || spaceQueue?.queued?.length);
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

  const loadVideos = useCallback(async (options?: { quiet?: boolean }) => {
    if (!options?.quiet) {
      setIsLoading(true);
    }
    setError("");
    try {
      const payload = await fetchVideos(activeDbId);
      setVideos(payload.videos);
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
    const groups = new Map<string, OwnerGroup>();

    for (const video of videos) {
      const key = ownerKey(video);
      const existing = groups.get(key);
      if (existing) {
        existing.bvids.push(video.bvid);
        existing.videoCount += 1;
        existing.commentCount += video.comment_total_count || 0;
        existing.danmakuCount += video.danmaku_count || 0;
      } else {
        groups.set(key, {
          bvids: [video.bvid],
          key,
          name: ownerName(video),
          ownerMid: (video.owner_mid || "").trim(),
          videoCount: 1,
          commentCount: video.comment_total_count || 0,
          danmakuCount: video.danmaku_count || 0,
        });
      }
    }

    return Array.from(groups.values()).sort((first, second) => {
      if (second.videoCount !== first.videoCount) return second.videoCount - first.videoCount;
      if (second.commentCount !== first.commentCount) return second.commentCount - first.commentCount;
      return first.name.localeCompare(second.name, "zh-Hans-CN");
    });
  }, [videos]);

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

  async function exportOwnerDatabase(owner = selectedOwner, format: ExportFormat) {
    if (!owner || !owner.bvids.length) return;
    setExportingKey(`owner:${owner.key}`);
    setExportTarget(null);
    setError("");
    setMessage(`正在导出 ${owner.name} 的 UP 主${format === "json" ? " JSON 文件" : "独立数据库"}`);
    try {
      const payload = await exportDatabaseArchive({
        bvids: owner.ownerMid ? undefined : owner.bvids,
        db_id: activeDbId,
        format,
        label: owner.name,
        owner_mid: owner.ownerMid || undefined,
      });
      setMessage(
        `导出完成：${payload.relative_path}，${payload.video_count} 个视频，${formatBytes(payload.size_bytes)}`,
      );
      setNotice({
        kind: "success",
        title: format === "json" ? "UP 主 JSON 导出完成" : "UP 主数据库导出完成",
        message:
          format === "json"
            ? `${payload.relative_path} 已导出为 JSON 数据文件，可再次导入`
            : `${payload.relative_path} 已加入热插拔目录`,
      });
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
        video_count: owner.bvids.length,
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
        label: `${video.bvid}_${video.title}`,
      });
      setMessage(`导出完成：${payload.relative_path}，${formatBytes(payload.size_bytes)}`);
      setNotice({
        kind: "success",
        title: format === "json" ? "视频 JSON 导出完成" : "视频数据库导出完成",
        message:
          format === "json"
            ? `${payload.relative_path} 已导出为 JSON 数据文件，可再次导入`
            : `${payload.relative_path} 已加入热插拔目录`,
      });
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

  async function runParse(target: string) {
    const targetBvid = extractBvid(target);
    logClientEvent("client.user.parse.start", "user started video parse", {
      bvid: targetBvid,
      db_id: activeDbId,
      delay: parseDelay,
      source: duplicateVideo ? "duplicate_confirm" : "form",
    });
    setIsParsing(true);
    setDuplicateVideo(null);
    setPendingParseTarget("");
    setError("");
    setMessage("正在解析并抓取评论，评论较多时可能需要几十秒");
    try {
      window.localStorage.setItem("bilibili-comment-delay", String(parseDelay));
      const payload = await parseVideo(target, parseDelay, activeDbId);
      logClientEvent("client.user.parse.success", "video parse completed", {
        db_id: activeDbId,
        bvid: payload.bvid,
        scraped_count: payload.scraped_count,
        after_count: payload.after_count,
        danmaku_count: payload.danmaku_count,
      });
      setMessage(
        `解析完成：本次抓到 ${payload.scraped_count} 条评论和 ${payload.danmaku_count ?? 0} 条弹幕，档案共 ${
          payload.after_count
        } 条，未返回 ${
          payload.deleted_count ?? 0
        } 条`,
      );
      window.history.pushState({}, "", dbPath(`/video/${payload.bvid}`, activeDbId));
      window.dispatchEvent(new PopStateEvent("popstate"));
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
    <main className="min-h-screen bg-[#f4f7fb] text-ink">
      <section className="border-b border-line bg-white">
        <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span className="inline-flex items-center gap-1">
                <Database size={15} aria-hidden="true" />
                评论视频库
              </span>
              <span>{videos.length} 个视频</span>
              <span>{formatNumber(totals.comments)} 条评论档案</span>
              {activeDatabase && <span>当前库：{activeDatabase.name}</span>}
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal text-ink lg:text-3xl">
              Bilibili 评论弹幕管理
            </h1>
          </div>
          <div className="flex items-center gap-2 self-center">
            <button
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              type="button"
              onClick={() => {
                logClientEvent("client.user.videos.refresh_click", "user refreshed video list", {
                  db_id: activeDbId,
                  video_count: videos.length,
                });
                void refreshDatabaseCatalog();
              }}
              disabled={isLoading || isLoadingDatabases}
            >
              <RefreshCcw className={cn((isLoading || isLoadingDatabases) && "animate-spin")} size={16} aria-hidden="true" />
              刷新列表
            </button>
            <button
              className={cn(
                "inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line bg-white px-4 text-sm font-medium transition",
                showSettings ? "border-bilibili text-bilibili" : "text-muted hover:border-ink hover:text-ink",
              )}
              type="button"
              onClick={() => {
                logClientEvent("client.user.settings.toggle", "user toggled parse settings", {
                  show_settings: !showSettings,
                });
                setShowSettings((value) => !value);
              }}
            >
              <Settings size={16} aria-hidden="true" />
              设置
            </button>
          </div>
        </div>
      </section>

      {error && (
        <section className="border-b border-red-100 bg-red-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-red-700 lg:px-6">{error}</div>
        </section>
      )}

      {message && !error && (
        <section className="border-b border-cyan-100 bg-cyan-50">
          <div className="mx-auto max-w-[1540px] px-4 py-2 text-sm text-cyan-700 lg:px-6">{message}</div>
        </section>
      )}

      {isParsing && <ProgressBanner progress={parseProgress} fallback="正在抓取评论和弹幕" />}
      {hasSpaceQueueWork && <ProgressBanner progress={spaceProgress} fallback="正在归档 UP 主全部视频" />}

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-6 lg:px-6">
        <StatTile icon={PlayCircle} label="视频数量" value={videos.length} tone="pink" />
        <StatTile icon={Eye} label="播放量" value={totals.views} tone="mint" />
        <StatTile icon={MessageCircle} label="评论档案" value={totals.comments} tone="cyan" />
        <StatTile icon={AlertTriangle} label="仍可见 / 未返回" value={`${totals.active} / ${totals.deleted}`} tone="mint" />
        <StatTile icon={Sparkles} label="弹幕档案" value={totals.danmaku} tone="amber" />
        <StatTile icon={Heart} label="评论点赞" value={totals.likes} tone="amber" />
      </section>

      <section className="mx-auto max-w-[1540px] px-4 pb-4 lg:px-6">
        <ManagementPanel
          activeDbId={activeDbId}
          databases={databases}
          hotplugDir={hotplugDir}
          importPath={importPath}
          isImporting={isImporting}
          isLoading={isLoadingDatabases}
          legacyExportDir={legacyExportDir}
          queue={spaceQueue}
          view={managementView}
          onImportPathChange={setImportPath}
          onPickFiles={() => fileInputRef.current?.click()}
          onPickFolder={() => folderInputRef.current?.click()}
          onRefresh={() => void refreshDatabaseCatalog()}
          onSelect={setActiveDatabase}
          onViewChange={setManagementView}
          onSubmitImport={submitDatabaseImport}
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

      <section className="mx-auto grid max-w-[1540px] gap-4 px-4 pb-6 lg:grid-cols-[420px_minmax(0,1fr)] lg:px-6">
        <aside className="self-start rounded-md border border-line bg-white p-4 shadow-soft">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <PlusCircle size={18} aria-hidden="true" />
            解析新视频
          </h2>
          <form className="mt-4 grid gap-3" onSubmit={submitParse}>
            <label className="grid gap-2 text-sm text-muted">
              视频链接或 BV 号
              <span className="flex h-11 min-w-0 items-center gap-2 rounded-md border border-line px-3 focus-within:border-bilibili focus-within:ring-2 focus-within:ring-pink-100">
                <LinkIcon size={16} aria-hidden="true" />
                <input
                  className="min-w-0 flex-1 bg-transparent text-ink outline-none"
                  placeholder="https://www.bilibili.com/video/BV..."
                  value={url}
                  onChange={(event) => {
                    setUrl(event.target.value);
                    setDuplicateVideo(null);
                    setPendingParseTarget("");
                  }}
                />
              </span>
            </label>
            <button
              className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
              type="submit"
              disabled={isTaskBusy}
            >
              <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
              {isParsing ? "解析中" : "解析视频"}
            </button>
          </form>
          {duplicateVideo && (
            <div className="mt-4 grid gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-ink">
              <div className="flex min-w-0 items-start gap-2">
                <AlertTriangle className="mt-0.5 shrink-0 text-amber-600" size={17} aria-hidden="true" />
                <div className="min-w-0">
                  <div className="font-medium text-amber-900">该视频已在本地档案中</div>
                  <div className="mt-1 line-clamp-2 text-amber-800">{duplicateVideo.title}</div>
                  <div className="mt-1 text-xs text-amber-700">
                    {duplicateVideo.bvid} · 档案 {formatNumber(duplicateVideo.comment_total_count)} · 弹幕{" "}
                    {formatNumber(duplicateVideo.danmaku_count)}
                  </div>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 transition hover:border-amber-500"
                  type="button"
                  onClick={() => openVideo(duplicateVideo)}
                >
                  <FolderOpen size={16} aria-hidden="true" />
                  打开已有档案
                </button>
                <button
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-3 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
                  type="button"
                  disabled={isTaskBusy}
                  onClick={() => {
                    logClientEvent("client.user.parse.duplicate_confirm", "user confirmed reparsing existing video", {
                      bvid: duplicateVideo.bvid,
                    });
                    void runParse(pendingParseTarget);
                  }}
                >
                  <RefreshCcw className={cn(isParsing && "animate-spin")} size={16} aria-hidden="true" />
                  重新抓取
                </button>
              </div>
            </div>
          )}
          <div className="mt-4 border-t border-line pt-4">
            <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
              <Users size={18} aria-hidden="true" />
              抓取UP主
            </h2>
            <form className="mt-4 grid gap-3" onSubmit={submitSpaceArchive}>
              <label className="grid gap-2 text-sm text-muted">
                UP 主主页或 mid
                <span className="flex h-11 min-w-0 items-center gap-2 rounded-md border border-line px-3 focus-within:border-bilibili focus-within:ring-2 focus-within:ring-pink-100">
                  <LinkIcon size={16} aria-hidden="true" />
                  <input
                    className="min-w-0 flex-1 bg-transparent text-ink outline-none"
                    placeholder="https://space.bilibili.com/123456"
                    value={ownerRef}
                    onChange={(event) => setOwnerRef(event.target.value)}
                  />
                </span>
              </label>
              <button
                className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-bilibili px-4 text-sm font-medium text-white transition hover:bg-[#e85f89] disabled:cursor-wait disabled:opacity-70"
                type="submit"
                disabled={isSubmittingSpace}
              >
                <RefreshCcw className={cn((isSubmittingSpace || hasSpaceQueueWork) && "animate-spin")} size={16} aria-hidden="true" />
                {isSubmittingSpace ? "加入队列中" : "抓取全部视频"}
              </button>
            </form>
          </div>
          {showSettings && (
            <div className="mt-4 grid gap-3 border-t border-line pt-4">
              <label className="grid gap-2 text-sm text-muted">
                抓取延迟
                <span className="flex h-10 items-center gap-3 rounded-md border border-line px-3">
                  <input
                    className="min-w-0 flex-1 accent-bilibili"
                    max={2}
                    min={0}
                    step={0.05}
                    type="range"
                    value={parseDelay}
                    onChange={(event) => setParseDelay(Number(event.target.value))}
                  />
                  <span className="w-14 text-right font-medium text-ink">{parseDelay.toFixed(2)}s</span>
                </span>
              </label>
              <div className="grid gap-2 text-sm">
                <InfoRow label="Cookie" value="data/cookie.txt" />
                <InfoRow label="当前数据库" value={activeDatabase?.relative_path || "data/comment_danmaku.db"} />
                <InfoRow label="热插拔目录" value={hotplugDir} />
              </div>
            </div>
          )}
          <div className="mt-4 border-t border-line pt-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <Users size={18} aria-hidden="true" />
                UP主分类
              </h2>
              <span className="text-xs text-muted">{ownerGroups.length} 位</span>
            </div>
            <div className="mt-3 grid gap-2">
              <OwnerFilterButton
                active={ownerFilter === "all"}
                commentCount={totals.comments}
                danmakuCount={totals.danmaku}
                name="全部视频"
                videoCount={videos.length}
                onClick={() => {
                  logClientEvent("client.user.videos.owner_filter", "user selected all owners", {
                    owner: "all",
                  });
                  setOwnerFilter("all");
                }}
              />
              <div className="max-h-[360px] overflow-y-auto pr-1">
                <div className="grid gap-2">
                  {ownerGroups.map((owner) => (
                    <OwnerFilterButton
                      active={ownerFilter === owner.key}
                      commentCount={owner.commentCount}
                      danmakuCount={owner.danmakuCount}
                      exportDisabled={Boolean(exportingKey)}
                      exporting={exportingKey === `owner:${owner.key}`}
                      key={owner.key}
                      name={owner.name}
                      videoCount={owner.videoCount}
                      onExport={() => setExportTarget({ kind: "owner", owner })}
                      onClick={() => {
                        logClientEvent("client.user.videos.owner_filter", "user selected owner filter", {
                          owner: owner.name,
                          video_count: owner.videoCount,
                        });
                        setOwnerFilter(owner.key);
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section className="flex min-h-[560px] min-w-0 flex-col rounded-md border border-line bg-white shadow-soft">
          <div className="border-b border-line p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
                <ListTree size={18} aria-hidden="true" />
                {selectedOwnerName ? `${selectedOwnerName}的视频` : "视频列表"}
              </h2>
              <span className="text-sm text-muted">
                {filteredVideos.length} / {videos.length}
              </span>
              <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-line px-3 text-sm text-muted">
                <Search size={16} aria-hidden="true" />
                <input
                  className="min-w-0 bg-transparent text-ink outline-none"
                  placeholder="搜索标题、UP 或 BV"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            </div>
          </div>

          <div className="grid max-h-[70vh] min-h-[420px] content-start gap-3 overflow-y-auto p-4">
            {isLoading && <div className="p-6 text-center text-sm text-muted">正在载入视频库</div>}
            {!isLoading &&
              filteredVideos.map((video) => (
                <VideoCard
                  disabled={Boolean(exportingKey)}
                  dbId={activeDbId}
                  exporting={exportingKey === `video:${video.bvid}`}
                  key={video.bvid}
                  video={video}
                  onExport={() => setExportTarget({ kind: "video", video })}
                />
              ))}
            {!isLoading && filteredVideos.length === 0 && (
              <div className="p-6 text-center text-sm text-muted">暂无匹配的视频</div>
            )}
          </div>
        </section>
      </section>
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
      {notice && <NoticeDialog notice={notice} onClose={() => setNotice(null)} />}
    </main>
  );
}
