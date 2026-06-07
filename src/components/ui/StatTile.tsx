import type { LucideIcon } from "lucide-react";
import { formatNumber } from "../../lib/utils";

type StatTileProps = {
  icon: LucideIcon;
  label: string;
  value?: number | string;
  tone?: "pink" | "cyan" | "mint" | "amber";
};

const toneClass = {
  pink: "bg-pink-50 text-bilibili",
  cyan: "bg-cyan-50 text-cyan",
  mint: "bg-emerald-50 text-mint",
  amber: "bg-amber-50 text-amber",
};

export function StatTile({ icon: Icon, label, value = 0, tone = "pink" }: StatTileProps) {
  return (
    <div className="min-h-24 rounded-md border border-line bg-panel p-4 shadow-soft">
      <div className="flex items-center gap-3">
        <span className={`grid h-9 w-9 place-items-center rounded-md ${toneClass[tone]}`}>
          <Icon size={18} aria-hidden="true" />
        </span>
        <span className="text-sm text-muted">{label}</span>
      </div>
      <div className="mt-4 text-2xl font-semibold tracking-normal text-ink">
        {typeof value === "number" ? formatNumber(value) : value}
      </div>
    </div>
  );
}
