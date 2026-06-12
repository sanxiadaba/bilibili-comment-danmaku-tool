import { ProgressBanner } from "../common";
import type { ProgressState } from "../../types";

type StatusStripsProps = {
  error: string;
  hasSpaceQueueWork: boolean;
  isParsing: boolean;
  message: string;
  parseProgress: ProgressState | null;
  spaceProgress: ProgressState | null;
};

export function StatusStrips({
  error,
  hasSpaceQueueWork,
  isParsing,
  message,
  parseProgress,
  spaceProgress,
}: StatusStripsProps) {
  return (
    <>
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
    </>
  );
}
