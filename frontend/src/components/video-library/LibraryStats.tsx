import { AlertTriangle, Eye, Heart, MessageCircle, PlayCircle, Sparkles } from "lucide-react";
import { StatTile } from "../ui/StatTile";

export type LibraryTotals = {
  views: number;
  comments: number;
  active: number;
  deleted: number;
  likes: number;
  danmaku: number;
};

type LibraryStatsProps = {
  totals: LibraryTotals;
  videoCount: number;
};

export function LibraryStats({ totals, videoCount }: LibraryStatsProps) {
  return (
    <section className="mx-auto grid max-w-[1540px] gap-4 px-4 py-4 md:grid-cols-2 lg:grid-cols-6 lg:px-6">
      <StatTile icon={PlayCircle} label="视频数量" value={videoCount} tone="pink" />
      <StatTile icon={Eye} label="播放量" value={totals.views} tone="mint" />
      <StatTile icon={MessageCircle} label="评论档案" value={totals.comments} tone="cyan" />
      <StatTile icon={AlertTriangle} label="仍可见 / 未返回" value={`${totals.active} / ${totals.deleted}`} tone="mint" />
      <StatTile icon={Sparkles} label="弹幕档案" value={totals.danmaku} tone="amber" />
      <StatTile icon={Heart} label="评论点赞" value={totals.likes} tone="amber" />
    </section>
  );
}
