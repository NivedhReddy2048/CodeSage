/**
 * WCAG 2.1 contrast arithmetic over the colour literals in globals.css.
 *
 * Only what the tokens use is supported: #rgb, #rrggbb and rgba(). A translucent
 * colour is composited over the layers beneath it before measuring, because that is
 * what the eye sees - a 14% rose wash over a navy card, not the wash alone.
 */

export type Rgba = { r: number; g: number; b: number; a: number };

export function parseColor(value: string): Rgba {
  const text = value.trim().toLowerCase();
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join("") : hex[1];
    return {
      r: parseInt(digits.slice(0, 2), 16),
      g: parseInt(digits.slice(2, 4), 16),
      b: parseInt(digits.slice(4, 6), 16),
      a: 1,
    };
  }
  const rgba = text.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/);
  if (rgba) {
    return {
      r: Number(rgba[1]),
      g: Number(rgba[2]),
      b: Number(rgba[3]),
      a: rgba[4] === undefined ? 1 : Number(rgba[4]),
    };
  }
  throw new Error(`Unsupported colour: ${value}`);
}

/** Paint `layers` bottom to top; the bottom layer must be opaque. */
export function composite(layers: Rgba[]): Rgba {
  const [base, ...rest] = layers;
  if (!base || base.a !== 1) throw new Error("The bottom layer must be opaque");
  return rest.reduce(
    (below, top) => ({
      r: top.r * top.a + below.r * (1 - top.a),
      g: top.g * top.a + below.g * (1 - top.a),
      b: top.b * top.a + below.b * (1 - top.a),
      a: 1,
    }),
    base,
  );
}

function channel(value: number) {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance({ r, g, b }: Rgba) {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: Rgba, b: Rgba) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * The custom properties of each theme block in a stylesheet, with var()
 * references resolved. Dark inherits light's values and overrides them, as the
 * cascade does on <html class="dark">.
 */
export function themeTokens(css: string) {
  const blocks = { light: {} as Record<string, string>, dark: {} as Record<string, string> };
  const rule = /(^|\n)([^{}\n]*?)\s*\{([^{}]*)\}/g;
  for (const match of css.matchAll(rule)) {
    const selectors = match[2].split(",").map((s) => s.trim());
    const targets = [
      ...(selectors.includes(":root") ? [blocks.light, blocks.dark] : []),
      ...(selectors.includes(".dark") ? [blocks.dark] : []),
    ];
    if (!targets.length) continue;
    // Only `--name: value;` declarations; comments are stripped first.
    const body = match[3].replace(/\/\*[\s\S]*?\*\//g, "");
    for (const declaration of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
      for (const target of targets) target[declaration[1]] = declaration[2].trim();
    }
  }

  const resolve = (tokens: Record<string, string>, name: string, seen: string[] = []): string => {
    const raw = tokens[name];
    if (raw === undefined) throw new Error(`Unknown token --${name}`);
    const ref = raw.match(/^var\(--([\w-]+)\)$/);
    if (!ref) return raw;
    if (seen.includes(ref[1])) throw new Error(`Circular token --${name}`);
    return resolve(tokens, ref[1], [...seen, name]);
  };

  return {
    light: (name: string) => resolve(blocks.light, name),
    dark: (name: string) => resolve(blocks.dark, name),
  };
}
