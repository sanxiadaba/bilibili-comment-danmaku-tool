import { Clock3, Sparkles, ThumbsUp } from "lucide-react";
import type { DanmakuItem } from "../../types";
import { formatFullDateTime } from "../../lib/utils";
import { DetailMetric } from "../common";
import { InfoRow } from "../common";
import { OwnerBadge } from "../common";
import { ColorSwatch } from "./ColorSwatch";
import { colorNameForDanmaku, formatProgress, getDanmakuModeLabel } from "./danmakuUtils";

type DanmakuDetailProps = {
  item: DanmakuItem;
};

export function DanmakuDetail({ item }: DanmakuDetailProps) {
  const createdAt = item.ctime ? formatFullDateTime(new Date(item.ctime * 1000).toISOString()) : "-";
  return (
    <div>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-11 w-20 shrink-0 items-center justify-center rounded-md bg-amber-50 text-base font-semibold text-amber">
            {formatProgress(item.progress)}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="break-words text-lg font-semibold leading-7 text-ink">{item.content}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
              {item.is_up_owner && <OwnerBadge />}
              <span>{getDanmakuModeLabel(item.mode)}</span>
              <ColorSwatch color={item.color} />
              <span>字号 {item.font_size}</span>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <DetailMetric icon={Clock3} label="视频时间" value={formatProgress(item.progress)} />
          <DetailMetric icon={Sparkles} label="模式" value={getDanmakuModeLabel(item.mode)} />
          <DetailMetric icon={ThumbsUp} label="点赞" value={item.like_count || 0} />
        </div>
      </div>

      <div className="border-b border-line p-4">
        <h3 className="text-sm font-semibold text-ink">显示信息</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="颜色" value={colorNameForDanmaku(item.color)} />
          <InfoRow label="字号" value={String(item.font_size)} />
          <InfoRow label="弹幕池" value={String(item.pool)} />
          <InfoRow label="发送时间" value={createdAt} />
        </dl>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-ink">原始标识</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="dmid" value={item.dmid} />
          <InfoRow label="bvid" value={item.bvid} />
          <InfoRow label="cid" value={item.cid || "-"} />
          <InfoRow label="入库时间" value={formatFullDateTime(item.fetched_at)} />
        </dl>
      </div>
    </div>
  );
}
