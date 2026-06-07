import { colorNameForDanmaku, colorNumberToHex } from "./danmakuUtils";

type ColorSwatchProps = {
  color: number;
};

export function ColorSwatch({ color }: ColorSwatchProps) {
  const label = colorNameForDanmaku(color);
  return (
    <span className="inline-flex items-center gap-1.5">
      <i
        className="h-3.5 w-3.5 rounded-sm border border-line"
        style={{ backgroundColor: colorNumberToHex(color) }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
