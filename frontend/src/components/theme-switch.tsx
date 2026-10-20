"use client";

import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { THEME_OPTIONS } from "@/components/theme-toggle-options";

const subscribe = () => () => undefined;

/**
 * No class merger here, on purpose: this is a landing-page island (see SignInButton).
 *
 * Light / dark / system as three icon radios in one pill: the public pages' theme
 * control. Native radios, so arrow keys and the group's accessible name come free,
 * and no menu library loads on the landing page. The choice is only shown once
 * mounted - the server cannot know the stored theme.
 */
export function ThemeSwitch({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const selected = mounted ? (theme ?? "system") : null;

  return (
    <fieldset className={`min-w-0 ${className ?? ""}`}>
      <legend className="sr-only">Theme</legend>
      <div className="flex items-center gap-0.5 rounded-full border bg-surface-1 p-0.5">
        {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
          <label
            key={value}
            title={label}
            data-checked={selected === value || undefined}
            className="flex size-7 cursor-pointer items-center justify-center rounded-full text-fg-secondary transition-colors hover:text-fg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-focus data-checked:bg-surface-2 data-checked:text-fg dark:data-checked:bg-surface-3"
          >
            <input
              type="radio"
              name="theme"
              value={value}
              className="sr-only"
              checked={selected === value}
              onChange={() => setTheme(value)}
              aria-label={label}
            />
            <Icon aria-hidden="true" className="size-3.5" />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
