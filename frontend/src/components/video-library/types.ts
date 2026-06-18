import type { DatabaseInfo } from "../../types";

export type ManagementView = "queue" | "database" | "auth";
export type LibraryView = "videos" | "manage" | "tasks" | "databases" | "auth";
export type NoticeState = {
  kind: "success" | "error" | "warning";
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
};

export type DatabaseSelectHandler = (database: DatabaseInfo) => void;
