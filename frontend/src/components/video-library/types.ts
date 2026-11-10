export type LibraryView = "videos" | "manage" | "tasks" | "databases" | "auth";
export type NoticeState = {
  kind: "success" | "error" | "warning";
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
};

