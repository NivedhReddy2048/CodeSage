"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

/**
 * Light, dark, or follow the system - "system" by default, so a first visit
 * matches the OS. next-themes sets the `.dark` class before first paint, which is
 * what avoids a light flash on a dark machine.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="codesage.theme"
    >
      {children}
    </NextThemesProvider>
  );
}
