import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { composite, contrastRatio, parseColor, themeTokens } from "@/lib/contrast";

/**
 * Every colour pairing the UI actually draws, measured against WCAG 2.1 AA in both
 * themes. Text needs 4.5:1; icons, control boundaries, chart marks and the focus
 * ring need 3:1 (1.4.11). Decorative separators - card edges, table dividers,
 * badge outlines - are exempt under 1.4.11 and not listed.
 *
 * A pair is `[foreground, backgroundLayers, minimum]`; layers are painted bottom to
 * top, so a translucent badge fill is measured over the surface it sits on.
 * `npm run contrast` prints every ratio.
 */

const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");
const tokens = themeTokens(css);

type Pair = [fg: string, bg: string[], min: number, only?: "light" | "dark"];

const SURFACES = ["canvas", "surface-1", "surface-2", "surface-3"];
const STATUSES = ["ok", "blocking", "nit", "running", "neutral"];

const PAIRS: Pair[] = [
  // Body text on every surface, and on a hovered menu item.
  ...[...SURFACES, "surface-hover"].flatMap((bg): Pair[] => [
    ["text-primary", [bg], 4.5],
    ["text-secondary", [bg], 4.5],
  ]),
  // text-muted: canvas and cards in light (by design), every surface in dark.
  ["text-muted", ["canvas"], 4.5],
  ["text-muted", ["surface-1"], 4.5],
  ["text-muted", ["surface-2"], 4.5, "dark"],
  ["text-muted", ["surface-3"], 4.5, "dark"],
  // Input placeholders, on the input fill.
  ["text-placeholder", ["surface-2"], 4.5],
  // The sticky top bar, glass over the canvas.
  ["text-primary", ["canvas", "glass"], 4.5],
  ["text-secondary", ["canvas", "glass"], 4.5],
  // Brand as text: links, highlights, the active nav item.
  ...["canvas", "surface-1", "surface-2"].flatMap((bg): Pair[] => [
    ["brand-primary", [bg], 4.5],
    ["brand-accent", [bg], 4.5],
  ]),
  ["brand-primary", ["surface-1", "brand-tinted"], 4.5],
  // The unread count on the bell: text on a solid blocking fill.
  ["on-blocking", ["status-blocking"], 4.5],
  // The landing page's closing band, on brand-deep.
  ["text-primary", ["brand-deep"], 4.5],
  ["text-secondary", ["brand-deep"], 4.5],
  // Primary button, at rest and hovered.
  ["on-brand", ["brand-primary"], 4.5],
  ["on-brand", ["brand-primary-hover"], 4.5],
  // Status badges, on every surface they appear on; status text and icons bare.
  ...STATUSES.flatMap((s): Pair[] => [
    ...["canvas", "surface-1", "surface-2"].map(
      (bg): Pair => [`status-${s}`, [bg, `status-${s}-bg`], 4.5],
    ),
    [`status-${s}`, ["surface-1"], 4.5],
    [`status-${s}`, ["surface-3"], 4.5],
  ]),
  // Non-text: focus ring, control boundaries, chart marks.
  ...SURFACES.map((bg): Pair => ["focus", [bg], 3]),
  ...["canvas", "surface-1", "surface-2"].map((bg): Pair => ["control-border", [bg], 3]),
  ...["chart-primary", "chart-secondary", "chart-blocking", "chart-nit"].map(
    (mark): Pair => [mark, ["surface-1"], 3],
  ),
  // The 2px active-item indicator in the sidebar.
  ["brand-primary", ["surface-2"], 3],
  // The chosen segment of a segmented control (surface-3 in dark).
  ["brand-primary", ["surface-3"], 4.5, "dark"],
];

const rows = (["light", "dark"] as const).flatMap((theme) =>
  PAIRS.filter(([, , , only]) => !only || only === theme).map(([fg, bg, min]) => {
    const value = (name: string) => parseColor(tokens[theme](name));
    const ratio = contrastRatio(value(fg), composite(bg.map(value)));
    return { theme, fg, bg: bg.join(" + "), min, ratio };
  }),
);

describe("theme contrast (WCAG 2.1 AA)", () => {
  it.each(rows.map((row) => [`${row.theme} · ${row.fg} on ${row.bg} · ${row.ratio.toFixed(2)}:1 (min ${row.min})`, row]))(
    "%s",
    (_name, row) => {
      expect(row.ratio).toBeGreaterThanOrEqual(row.min);
    },
  );
});

describe("contrast arithmetic", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio(parseColor("#fff"), parseColor("#000000"))).toBeCloseTo(21, 5);
    expect(contrastRatio(parseColor("#ffffff"), parseColor("#767676"))).toBeCloseTo(4.54, 2);
  });

  it("composites a translucent layer over the surface beneath it", () => {
    const mixed = composite([parseColor("#000000"), parseColor("rgba(255, 255, 255, 0.5)")]);
    expect(mixed.r).toBeCloseTo(127.5);
  });

  it("reads each theme's own value, with dark overriding light", () => {
    expect(tokens.light("on-brand")).toBe("#ffffff");
    expect(tokens.dark("on-brand")).toBe("#04120c");
    expect(tokens.dark("primary-foreground")).toBe("#04120c");
  });
});
