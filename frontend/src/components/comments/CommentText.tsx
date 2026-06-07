import type { CommentNode } from "../../types";
import { cn, getCommentPictures, getCommentTextParts } from "../../lib/utils";

type CommentTextProps = {
  comment?: CommentNode;
  normalized?: CommentNode["normalized"];
  className?: string;
};

export function CommentText({ comment, normalized, className }: CommentTextProps) {
  const data = normalized || comment?.normalized;
  if (!data) return null;
  const parts = getCommentTextParts(data);

  return (
    <p className={className}>
      {parts.map((part, index) => {
        if (part.type === "text") {
          return <span key={`${part.text}-${index}`}>{part.text}</span>;
        }

        const large = part.size && part.size > 1;
        return (
          <img
            className={cn("mx-0.5 inline-block align-[-0.28em]", large ? "h-12 max-w-24" : "h-5 w-5")}
            src={part.url}
            alt={part.text}
            title={part.title}
            loading="eager"
            referrerPolicy="no-referrer"
            key={`${part.text}-${index}`}
          />
        );
      })}
    </p>
  );
}

type CommentImagesProps = {
  comment: CommentNode;
  compact?: boolean;
};

export function CommentImages({ comment, compact = false }: CommentImagesProps) {
  const pictures = getCommentPictures(comment);
  if (!pictures.length) return null;

  return (
    <div className={cn("mt-3 grid gap-2", compact ? "grid-cols-3" : "grid-cols-2")}>
      {pictures.map((picture, index) => (
        <a
          className={cn(
            "group relative block overflow-hidden rounded-md border border-line bg-slate-100 transition hover:border-bilibili",
            compact ? "aspect-square" : "aspect-[4/3]",
          )}
          href={picture.img_src}
          key={`${picture.img_src}-${index}`}
          target="_blank"
          rel="noreferrer"
        >
          <img
            className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
            src={picture.img_src}
            alt={`评论图片 ${index + 1}`}
            loading="eager"
            referrerPolicy="no-referrer"
          />
          {picture.play_gif_thumbnail && (
            <span className="absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
              GIF
            </span>
          )}
        </a>
      ))}
    </div>
  );
}
