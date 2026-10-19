import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Component tests run in jsdom. No React plugin: Vite's own transform handles JSX
// with the automatic runtime, and @vitejs/plugin-react's Babel 8 peer conflicts with
// the Babel 7 that Next.js pins.
export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
