import { UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { cn, normalizeImageUrl } from "../../lib/utils";

type AvatarProps = {
  src?: string;
  name?: string;
  size?: "sm" | "md" | "lg";
  href?: string;
  onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
};

const sizeClass = {
  sm: "h-7 w-7",
  md: "h-9 w-9",
  lg: "h-12 w-12",
};

export function Avatar({ src, name, size = "md", href, onClick }: AvatarProps) {
  const imageSrc = normalizeImageUrl(src);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [imageSrc]);

  const content = (
    <span className={cn("block overflow-hidden rounded-full bg-slate-100 text-muted", sizeClass[size])}>
      {imageSrc && !failed ? (
        <img
          className="h-full w-full object-cover"
          src={imageSrc}
          alt={name || ""}
          loading="eager"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="grid h-full w-full place-items-center">
          <UserRound size={size === "lg" ? 22 : 16} aria-hidden="true" />
        </span>
      )}
    </span>
  );

  if (href) {
    return (
      <a
        className="shrink-0 rounded-full outline-none ring-bilibili transition focus:ring-2"
        href={href}
        target="_blank"
        rel="noreferrer"
        title={name ? `打开 ${name} 的 Bilibili 主页` : "打开用户主页"}
        onClick={onClick}
      >
        {content}
      </a>
    );
  }

  return <div className="shrink-0">{content}</div>;
}
