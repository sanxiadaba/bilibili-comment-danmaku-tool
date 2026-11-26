import { AlertTriangle, Eye, Heart, MessageCircle, PlayCircle, Sparkles } from "lucide-react";
import { StatTile } from "../ui/StatTile";
import type { LibraryTotals, VideoTotals } from "../../lib/videoLibrary";

type LibraryStatsProps = {
  totals: VideoTotals;
  videoCount: number;
  /** How many rows are actually loaded; used to label values that only cover the loaded page. */
  loadedCount?: number;
  /** Where the comment/danmaku sums come from; defaults to the loaded page. */
  scope?: LibraryTotals["scope"];
};

export function LibraryStats({ totals, videoCount, loadedCount, scope = "loaded" }: LibraryStatsProps) {
  const partial = typeof loadedCount === "number" && loadedCount < videoCount;
  // 播放量、点赞和评论状态没有全库来源，只能按已加载的视频统计；标签里写明，避免冒充全库。
  const loadedSuffix = partial ? `（已加载 ${loadedCount} 条）` : "";
  const archiveSuffix = scope === "library" ? "（全库）" : loadedSuffix;

  return (
    <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-6 lg:px-6">
      <StatTile icon={PlayCircle} label="视频数量" value={videoCount} tone="pink" />
      <StatTile icon={Eye} label={`播放量${loadedSuffix}`} value={totals.views} tone="mint" />
      <StatTile icon={MessageCircle} label={`评论档案${archiveSuffix}`} value={totals.comments} tone="cyan" />
      <StatTile
        icon={AlertTriangle}
        label={`仍可见 / 未返回${loadedSuffix}`}
        value={`${totals.active} / ${totals.deleted}`}
        tone="mint"
      />
      <StatTile icon={Sparkles} label={`弹幕档案${archiveSuffix}`} value={totals.danmaku} tone="amber" />
      <StatTile icon={Heart} label={`评论点赞${loadedSuffix}`} value={totals.likes} tone="amber" />
    </section>
  );
}
