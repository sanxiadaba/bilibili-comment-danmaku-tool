import { ThumbsUp } from "lucide-react";
import type { CommentNode } from "../../types";
import {
  cleanIpLocation,
  cn,
  formatDateTime,
  getCommentAuthor,
  getCommentAvatar,
} from "../../lib/utils";
import { Avatar } from "../ui/Avatar";
import { DeletedBadge, OwnerBadge } from "./CommentBadges";
import { CommentImages, CommentText } from "./CommentText";
import { getBilibiliUserUrl } from "./commentUtils";

type CommentRowProps = {
  comment: CommentNode;
  active: boolean;
  onSelect: () => void;
};

export function CommentRow({ comment, active, onSelect }: CommentRowProps) {
  const normalized = comment.normalized;
  const profileUrl = getBilibiliUserUrl(normalized.mid);
  return (
    <button
      className={cn(
        "block w-full border-b border-line px-4 py-3 text-left transition hover:bg-[#fbfcfe]",
        active && "bg-pink-50",
        normalized.is_deleted && "bg-red-50/45 hover:bg-red-50",
      )}
      type="button"
      onClick={onSelect}
    >
      <div className="flex items-center gap-3">
        <Avatar
          name={getCommentAuthor(comment)}
          size="md"
          src={getCommentAvatar(comment)}
          href={profileUrl}
          onClick={(event) => event.stopPropagation()}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-ink">{getCommentAuthor(comment)}</span>
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-0.5 text-xs font-medium",
                normalized.level === 1 ? "bg-cyan-50 text-cyan" : "bg-amber-50 text-amber",
              )}
            >
              {normalized.level === 1 ? "一级" : "回复"}
            </span>
            {normalized.is_up_owner && <OwnerBadge />}
            {normalized.is_deleted && <DeletedBadge />}
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted">
            <span>{formatDateTime(normalized.time_iso)}</span>
            <span>{cleanIpLocation(normalized.ip_location)}</span>
            <span className="inline-flex items-center gap-1">
              <ThumbsUp size={12} aria-hidden="true" />
              {normalized.like || 0}
            </span>
          </div>
        </div>
      </div>
      <CommentText
        className={cn("mt-2 line-clamp-2 text-sm leading-6 text-[#344158]", normalized.is_deleted && "text-[#6b4750]")}
        comment={comment}
      />
      <CommentImages comment={comment} compact />
    </button>
  );
}
