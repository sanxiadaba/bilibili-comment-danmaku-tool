import type { DatabaseInfo, VideoSummary } from "../../types";

export type ManagementView = "queue" | "database" | "auth";
export type LibraryView = "videos" | "tasks" | "databases" | "auth";
export type ExportFormat = "sqlite" | "json";

export type OwnerGroup = {
  bvids: string[];
  key: string;
  name: string;
  ownerMid: string;
  videoCount: number;
  commentCount: number;
  danmakuCount: number;
};

export type ExportTarget = { kind: "owner"; owner: OwnerGroup } | { kind: "video"; video: VideoSummary };

export type NoticeState = {
  kind: "success" | "error" | "warning";
  title: string;
  message: string;
};

export type DatabaseSelectHandler = (database: DatabaseInfo) => void;
