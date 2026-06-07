import { Clock3, ListTree, MessageCircle, ThumbsUp } from "lucide-react";
import type { CommentNode, NormalizedComment } from "../../types";
import {
  cleanIpLocation,
  cn,
  flattenThread,
  formatDateTime,
  formatFullDateTime,
  getCommentAuthor,
  getCommentAvatar,
} from "../../lib/utils";
import { Avatar } from "../ui/Avatar";
import { DetailMetric } from "../common";
import { InfoRow } from "../common";
import { DeletedBadge, OwnerBadge } from "./CommentBadges";
import { CommentImages, CommentText } from "./CommentText";
import { getBilibiliUserUrl } from "./commentUtils";

type CommentDetailProps = {
  comment: CommentNode;
  threadItems: ReturnType<typeof flattenThread>;
  onSelect: (id: string) => void;
};

export function CommentDetail({ comment, threadItems, onSelect }: CommentDetailProps) {
  const normalized = comment.normalized;
  const profileUrl = getBilibiliUserUrl(normalized.mid);

  return (
    <div>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <Avatar name={getCommentAuthor(comment)} size="lg" src={getCommentAvatar(comment)} href={profileUrl} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold text-ink">{getCommentAuthor(comment)}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
              <span>UID {normalized.mid}</span>
              <span>{cleanIpLocation(normalized.ip_location)}</span>
              <span>{normalized.level === 1 ? "一级评论" : "楼中楼回复"}</span>
              {normalized.is_up_owner && <OwnerBadge />}
              {normalized.is_deleted && <DeletedBadge />}
            </div>
          </div>
        </div>

        <CommentText className="mt-4 whitespace-pre-wrap break-words text-base leading-7 text-[#253148]" comment={comment} />
        <CommentImages comment={comment} />

        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <DetailMetric icon={ThumbsUp} label="点赞" value={normalized.like || 0} />
          <DetailMetric icon={MessageCircle} label="回复" value={normalized.rcount || 0} />
          <DetailMetric icon={Clock3} label="时间" value={formatDateTime(normalized.time_iso)} />
        </div>
        {normalized.is_deleted && (
          <div className="mt-3 rounded-md border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
            最近一次刷新未返回这条评论，可能已被删除、折叠或接口暂未返回。最后可见：
            {formatFullDateTime(normalized.last_seen_at)}；首次未返回：
            {formatFullDateTime(normalized.missing_since)}。
          </div>
        )}
      </div>

      <div className="border-b border-line p-4">
        <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
          <ListTree size={16} aria-hidden="true" />
          当前线程
        </h3>
        <div className="mt-3 max-h-[340px] space-y-2 overflow-y-auto pr-1">
          {threadItems.map((item) => (
            <ThreadButton
              active={item.rpid === normalized.rpid}
              item={item}
              key={item.rpid}
              onSelect={() => onSelect(item.rpid)}
            />
          ))}
        </div>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-ink">原始标识</h3>
        <dl className="mt-3 grid gap-2 text-sm">
          <InfoRow label="rpid" value={normalized.rpid} />
          <InfoRow label="root" value={normalized.root} />
          <InfoRow label="parent" value={normalized.parent} />
          <InfoRow label="ctime" value={String(normalized.ctime)} />
          <InfoRow label="完整时间" value={formatFullDateTime(normalized.time_iso)} />
          <InfoRow label="最后可见" value={formatFullDateTime(normalized.last_seen_at)} />
          <InfoRow label="首次未返回" value={formatFullDateTime(normalized.missing_since)} />
        </dl>
      </div>
    </div>
  );
}

type ThreadButtonProps = {
  item: NormalizedComment;
  active: boolean;
  onSelect: () => void;
};

function ThreadButton({ item, active, onSelect }: ThreadButtonProps) {
  return (
    <button
      className={cn(
        "w-full rounded-md border border-line bg-[#fbfcfe] p-3 text-left transition hover:border-bilibili hover:bg-white",
        active && "border-bilibili bg-pink-50",
      )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-sm font-semibold text-ink">{item.user?.uname || "未命名用户"}</span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
          {item.is_up_owner && <OwnerBadge />}
          {item.is_deleted && <DeletedBadge />}
          {formatDateTime(item.time_iso)}
        </span>
      </div>
      <CommentText className="mt-1 line-clamp-3 text-sm leading-6 text-[#344158]" normalized={item} />
    </button>
  );
}
