import { Radio, Route, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * How a review runs, as the code runs it (backend/apps/agents/graph.py):
 *
 *   PR diff -> Diff/Intent -> [static analysis, security, correctness, grounding,
 *                              test coverage] -> synthesis -> GitHub
 *
 * Diff/Intent runs first and alone; the five analysis agents then run in parallel.
 * Each line of copy below is a claim about that code - keep them in step with it.
 */

type Stage = { title: string; detail: string[]; highlight?: boolean };

const AGENTS: Stage[] = [
  { title: "Static analysis", detail: ["ruff + bandit on Python", "a pattern scan on JS/TS"] },
  { title: "Security", detail: ["injection, secrets, unsafe", "deserialisation, auth checks"] },
  { title: "Correctness", detail: ["wrong conditions and variables,", "off-by-one, unhandled cases"] },
  {
    title: "Codebase grounding",
    detail: ["pgvector + Postgres full-text,", "fused by reciprocal rank fusion"],
    highlight: true,
  },
  { title: "Test coverage", detail: ["changed logic with no", "matching test change"] },
];

const DIFF: Stage = { title: "PR diff", detail: ["opened or pushed"] };
const INTENT: Stage = { title: "Diff/Intent", detail: ["classifies the change"] };
const SYNTHESIS: Stage = { title: "Synthesis", detail: ["merge, de-duplicate,", "rank Blocking / Nit"] };
const GITHUB: Stage = { title: "GitHub", detail: ["bot summary comment", "+ inline comments"] };

export const PIPELINE_BADGES = [
  { icon: Route, label: "Groq → Gemini fallback → labelled degraded mode" },
  { icon: Radio, label: "Live progress over WebSockets" },
  { icon: ShieldCheck, label: "Grounded citations checked; unsupported ones dropped" },
];

/* ---- Desktop: an SVG with data pulses along each lane ------------------------ */

const LANES = [70, 150, 230, 310, 390]; // agent row centres
const MID = 230;
const LANE_PERIOD = 3.6; // seconds for one pulse to cross; pulses are staggered evenly

function Node({
  x,
  y,
  w,
  h,
  stage,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  stage: Stage;
}) {
  const lines = stage.detail.length;
  const top = y + h / 2 - (lines * 16 + 20) / 2 + 15;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        className={cn(
          "fill-surface-1",
          stage.highlight ? "stroke-[color:var(--border-brand)]" : "stroke-[color:var(--border-default)]",
        )}
        strokeWidth={1}
      />
      <text x={x + 16} y={top} className="fill-fg text-[14px] font-semibold">
        {stage.title}
      </text>
      {stage.detail.map((line, index) => (
        <text key={line} x={x + 16} y={top + 20 + index * 16} className="fill-fg-secondary text-[12px]">
          {line}
        </text>
      ))}
    </g>
  );
}

function lanePath(cy: number) {
  return `M130 ${MID} L310 ${MID} C340 ${MID} 340 ${cy} 370 ${cy} L640 ${cy} C670 ${cy} 670 ${MID} 700 ${MID} L920 ${MID}`;
}

function DiagramSvg() {
  return (
    <svg
      viewBox="0 0 1080 460"
      aria-hidden="true"
      className="hidden h-auto w-full lg:block"
      focusable="false"
    >
      {/* Connectors */}
      <g fill="none" strokeWidth={1.5} className="stroke-[color:var(--border-strong)]">
        <path d={`M130 ${MID} H170`} />
        {LANES.map((cy) => (
          <path key={cy} d={`M310 ${MID} C340 ${MID} 340 ${cy} 370 ${cy}`} />
        ))}
        {LANES.map((cy) => (
          <path key={cy} d={`M640 ${cy} C670 ${cy} 670 ${MID} 700 ${MID}`} />
        ))}
        <path d={`M860 ${MID} H920`} />
      </g>

      {/* Data pulses: drawn under the nodes, so each disappears into a stage and
          comes out the other side. Hidden, not merely slowed, for reduced motion. */}
      <g className="motion-reduce:hidden">
        {LANES.map((cy, index) => (
          <circle key={cy} r={3.5} className="fill-brand-accent">
            <animateMotion
              dur={`${LANE_PERIOD}s`}
              begin={`-${(index * LANE_PERIOD) / LANES.length}s`}
              repeatCount="indefinite"
              path={lanePath(cy)}
              keyPoints="0;1"
              keyTimes="0;1"
              calcMode="linear"
            />
          </circle>
        ))}
      </g>

      <Node x={10} y={MID - 30} w={120} h={60} stage={DIFF} />
      <Node x={170} y={MID - 30} w={140} h={60} stage={INTENT} />
      {AGENTS.map((stage, index) => (
        <Node key={stage.title} x={370} y={LANES[index] - 32} w={270} h={64} stage={stage} />
      ))}
      <Node x={700} y={MID - 44} w={160} h={88} stage={SYNTHESIS} />
      <Node x={920} y={MID - 44} w={150} h={88} stage={GITHUB} />

      {/* "in parallel" bracket label above the fan */}
      <text x={505} y={18} textAnchor="middle" className="fill-fg-secondary text-[11px] font-medium tracking-[0.06em] uppercase">
        Five agents in parallel
      </text>
    </svg>
  );
}

/* ---- Below lg, and for assistive tech everywhere: an ordered list -------------- */

function StepCard({ stage, className }: { stage: Stage; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-surface-1 px-4 py-3 shadow-card",
        stage.highlight && "border-border-brand",
        className,
      )}
    >
      <p className="font-semibold text-fg">{stage.title}</p>
      <p className="text-sm text-fg-secondary">{stage.detail.join(" ")}</p>
    </div>
  );
}

function DiagramList() {
  const step = "relative pl-8 before:absolute before:top-3 before:left-[0.4375rem] before:size-2.5 before:rounded-full before:border-2 before:border-brand before:bg-canvas";
  return (
    <ol
      aria-label="Review pipeline, in order"
      className="relative space-y-3 lg:sr-only before:absolute before:top-4 before:bottom-4 before:left-3 before:w-px before:bg-[color:var(--border-strong)]"
    >
      <li className={step}>
        <StepCard stage={DIFF} />
      </li>
      <li className={step}>
        <StepCard stage={INTENT} />
      </li>
      <li className={step}>
        <p className="mb-2 pt-1.5 text-xs font-medium tracking-[0.06em] text-fg-secondary uppercase">
          Then five agents in parallel
        </p>
        <ul className="grid gap-3 sm:grid-cols-2">
          {AGENTS.map((stage) => (
            <li key={stage.title}>
              <StepCard stage={stage} className="h-full" />
            </li>
          ))}
        </ul>
      </li>
      <li className={step}>
        <StepCard stage={SYNTHESIS} />
      </li>
      <li className={step}>
        <StepCard stage={GITHUB} />
      </li>
    </ol>
  );
}

export function PipelineDiagram() {
  return (
    <figure className="m-0">
      <div className="rounded-2xl border bg-surface-2/50 p-4 sm:p-6 lg:p-8">
        <DiagramSvg />
        <DiagramList />
      </div>
      <figcaption className="mt-4 flex flex-wrap gap-2">
        {PIPELINE_BADGES.map(({ icon: Icon, label }) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 rounded-full border bg-surface-1 px-3 py-1 text-xs font-medium text-fg-secondary"
          >
            <Icon aria-hidden="true" className="size-3.5 text-brand" />
            {label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
