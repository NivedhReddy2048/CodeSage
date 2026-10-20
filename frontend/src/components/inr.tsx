/**
 * The rupee sign, set in the system UI font, for the public landing page.
 *
 * Geist carries ₹ (U+20B9) only in its latin-ext subset. One ₹ anywhere on a page
 * makes the browser fetch that subset for Geist and for Geist Mono - two extra font
 * files competing with the first paint. On /login that measurably cost Lighthouse
 * mobile 5-8 points (87-93 with them, 95-96 without). Every desktop and mobile
 * system UI font has ₹, so the glyph renders the same without them.
 */
export function Inr() {
  return <span className="font-[system-ui,sans-serif]">₹</span>;
}
