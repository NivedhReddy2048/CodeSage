import { createCn } from "cn/config";

/**
 * Class merging that knows the design system's own scales. Without this, a custom
 * size such as `text-control` reads as a text colour, and merging it with
 * `text-fg` silently dropped the font size.
 */
export const cn = createCn({
  extend: {
    classGroups: {
      "font-size": [{ text: ["display", "h1", "h2", "kpi", "body", "control", "micro"] }],
      shadow: [{ shadow: ["card", "popover"] }],
      ease: [{ ease: ["standard", "out-expo"] }],
    },
  },
});
