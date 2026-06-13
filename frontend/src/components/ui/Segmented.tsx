import { cn } from "../../lib/utils";

type Option<T extends string> = {
  label: string;
  value: T;
};

type SegmentedProps<T extends string> = {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
};

export function Segmented<T extends string>({ value, options, onChange, ariaLabel }: SegmentedProps<T>) {
  return (
    <div className="inline-flex h-9 rounded-md border border-line bg-[#f6f9fc]/90 p-1 shadow-inner" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          className={cn(
            "min-w-16 rounded px-3 text-sm font-medium text-muted transition hover:text-ink",
            value === option.value && "bg-white text-ink shadow-sm ring-1 ring-line",
          )}
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
