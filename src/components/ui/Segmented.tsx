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
    <div className="inline-flex h-9 rounded-md border border-line bg-white p-1" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          className={cn(
            "min-w-16 rounded px-3 text-sm font-medium text-muted transition",
            value === option.value && "bg-ink text-white shadow-sm",
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
