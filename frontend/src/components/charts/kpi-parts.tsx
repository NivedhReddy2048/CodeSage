/**
 * The small marks inside a KPI tile. Both are decorative summaries of numbers the
 * tile already states in text (and the dashboard's tables list in full), so they are
 * hidden from assistive tech and never carry meaning by colour alone.
 */

export type Segment = { label: string; value: number; color: string };

/**
 * A thin proportional bar - how a total splits - with its key underneath in text.
 * Zero segments are left out of the bar but kept out of the key too, so the key
 * lists exactly what is drawn. 2px surface gaps separate segments.
 */
export function BreakdownBar({ segments }: { segments: Segment[] }) {
  const shown = segments.filter((segment) => segment.value > 0);
  const total = shown.reduce((sum, segment) => sum + segment.value, 0);
  if (!total) return null;

  return (
    <div aria-hidden="true" className="mt-3">
      <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-[color:var(--chart-empty)]">
        {shown.map((segment) => (
          <span
            key={segment.label}
            className="first:rounded-l-full last:rounded-r-full"
            style={{ flexGrow: segment.value, flexBasis: 0, background: segment.color }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[0.6875rem] text-fg-secondary">
        {shown.map((segment) => (
          <span key={segment.label} className="inline-flex items-center gap-1">
            <span className="size-1.5 rounded-full" style={{ background: segment.color }} />
            <span className="font-mono tabular-nums">{segment.value}</span> {segment.label}
          </span>
        ))}
      </div>
    </div>
  );
}

const WIDTH = 120;
const HEIGHT = 28;

/**
 * A daily trend as a 2px line, stretched to the tile's width. Days with no value
 * (`null`) break the line rather than dropping to zero - a day with no completed
 * review has no review time, not a review time of zero. It draws nothing with fewer
 * than two values, or when most days have none.
 */
export function Sparkline({ values, color = "var(--chart-primary)" }: { values: (number | null)[]; color?: string }) {
  const known = values.filter((value): value is number => value !== null);
  // A trend needs enough days to be one: with most days empty, the line is a few
  // stray stubs that suggest a pattern the data does not have.
  if (known.length < 2 || known.length < values.length / 2) return null;

  const max = Math.max(...known);
  const min = Math.min(...known);
  const span = max - min || 1;
  const step = values.length > 1 ? WIDTH / (values.length - 1) : WIDTH;
  const y = (value: number) => HEIGHT - 3 - ((value - min) / span) * (HEIGHT - 6);

  // One polyline per unbroken run of known values.
  const runs: string[] = [];
  let run: string[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (run.length) runs.push(run.join(" "));
      run = [];
    } else {
      run.push(`${(index * step).toFixed(1)},${y(value).toFixed(1)}`);
    }
  });
  if (run.length) runs.push(run.join(" "));

  return (
    <svg
      aria-hidden="true"
      viewBox={`-3 0 ${WIDTH + 6} ${HEIGHT}`}
      className="mt-3 h-7 w-full overflow-visible"
      preserveAspectRatio="none"
    >
      {runs.map((points) => {
        // A lone day between gaps becomes a short stroke, so it is not lost.
        const line = points.includes(" ")
          ? points
          : (() => {
              const [x, py] = points.split(",").map(Number);
              return `${x - 1.5},${py} ${x + 1.5},${py}`;
            })();
        return (
          <polyline
            key={points}
            points={line}
            fill="none"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}
