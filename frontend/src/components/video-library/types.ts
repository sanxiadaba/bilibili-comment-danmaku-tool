import type { DatabaseInfo, OwnerGroup, VideoSummary } from "../../types";

export type ManagementView = "queue" | "database" | "auth";
export type LibraryView = "videos" | "manage" | "tasks" | "databases" | "auth";
export type ExportFormat = "sqlite" | "json";

export type ExportTarget = { kind: "owner"; owner: OwnerGroup } | { kind: "video"; video: VideoSummary };

export type DeleteTarget =
  | { kind: "owner"; owner: OwnerGroup }
  | { kind: "owners"; owners: OwnerGroup[] }
  | { kind: "video"; video: VideoSummary }
  | { kind: "videos"; videos: VideoSummary[] };

export type NoticeState = {
  kind: "success" | "error" | "warning";
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
};

export type DatabaseSelectHandler = (database: DatabaseInfo) => void;
