import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
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
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const preview = previewIndex === null ? null : pictures[previewIndex];
  const previewNumber = previewIndex === null ? 0 : previewIndex + 1;

  useEffect(() => {
    if (!preview) return undefined;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewIndex(null);
      }
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [preview]);

  if (!pictures.length) return null;

  return (
    <>
      <div className={cn("mt-3 grid gap-2", compact ? "grid-cols-3" : "grid-cols-2")}>
        {pictures.map((picture, index) => (
          <span
            className={cn(
              "group relative block cursor-zoom-in overflow-hidden rounded-md border border-line bg-slate-100 text-left transition hover:border-bilibili focus:outline-none focus:ring-2 focus:ring-bilibili/30",
              compact ? "aspect-square" : "aspect-[4/3]",
            )}
            key={`${picture.img_src}-${index}`}
            role={compact ? undefined : "button"}
            tabIndex={compact ? undefined : 0}
            onClick={(event) => {
              event.stopPropagation();
              setPreviewIndex(index);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              event.stopPropagation();
              setPreviewIndex(index);
            }}
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
          </span>
        ))}
      </div>
      {preview &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4"
            role="dialog"
            aria-modal="true"
            aria-label="评论图片预览"
            onClick={() => setPreviewIndex(null)}
          >
            <div className="relative max-h-full max-w-6xl" onClick={(event) => event.stopPropagation()}>
              <button
                className="absolute right-2 top-2 inline-flex h-9 w-9 items-center justify-center rounded-md bg-black/70 text-white transition hover:bg-black focus:outline-none focus:ring-2 focus:ring-white/70"
                type="button"
                aria-label="关闭图片预览"
                onClick={() => setPreviewIndex(null)}
              >
                <X size={20} aria-hidden="true" />
              </button>
              <img
                className="max-h-[88vh] max-w-[92vw] rounded-md bg-white object-contain shadow-2xl"
                src={preview.img_src}
                alt={`评论图片 ${previewNumber} 预览`}
                referrerPolicy="no-referrer"
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
