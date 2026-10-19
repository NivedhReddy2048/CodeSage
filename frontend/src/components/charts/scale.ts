/** A rounded axis maximum and its ticks: 0 / 5 / 10 / 15, never 0 / 4.7 / 9.4. */
export function niceScale(max: number, tickCount = 4) {
  if (!Number.isFinite(max) || max <= 0) return { max: 1, ticks: [0, 1] };
  const rough = max / tickCount;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? rough;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= top + step / 2; value += step) ticks.push(Number(value.toFixed(6)));
  return { max: top, ticks };
}

/** 1,284 -> "1.3K". Axis ticks and tile values compact from 1,000 up. */
export function compact(value: number) {
  if (Math.abs(value) < 1000) return String(Number(value.toFixed(2)));
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** A rect path with 4px rounded corners on the data end only, square at the baseline. */
export function columnPath(x: number, y: number, width: number, height: number, radius = 4) {
  if (height <= 0) return "";
  const r = Math.min(radius, width / 2, height);
  return [
    `M${x},${y + height}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${y + height}`,
    "Z",
  ].join(" ");
}

/** The horizontal twin: rounded on the right (data) end, square at the left baseline. */
export function barPath(x: number, y: number, width: number, height: number, radius = 4) {
  if (width <= 0) return "";
  const r = Math.min(radius, height / 2, width);
  return [
    `M${x},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${y + height - r}`,
    `Q${x + width},${y + height} ${x + width - r},${y + height}`,
    `H${x}`,
    "Z",
  ].join(" ");
}
