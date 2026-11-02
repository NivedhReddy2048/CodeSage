/**
 * The per-workspace daily review cap, for pages that render before anyone signs in
 * (the landing page cannot ask the API: the backend may still be waking up). Keep
 * NEXT_PUBLIC_DEMO_REVIEWS_PER_WORKSPACE equal to the backend's
 * DEMO_REVIEWS_PER_WORKSPACE_PER_DAY; signed-in pages read the real figure.
 */
export const DEMO_REVIEWS_PER_WORKSPACE = Number(process.env.NEXT_PUBLIC_DEMO_REVIEWS_PER_WORKSPACE ?? 5);

export function demoNote(perWorkspace: number) {
  return `Free demo, ${perWorkspace} reviews/day per workspace`;
}
