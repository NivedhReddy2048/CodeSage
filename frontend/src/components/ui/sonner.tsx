"use client"

import {
  CircleCheck,
  CircleX,
  Info,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react"
import { useTheme } from "next-themes"
import { Toaster as Sonner, type ToasterProps } from "sonner"

/**
 * Toasts for the outcome of an action ("Role changed", "Re-index started") - things
 * worth confirming that need no reply. Errors a person must act on stay inline,
 * next to what failed, where they do not disappear on a timer.
 *
 * sonner announces each toast in a polite live region, pauses its timer on hover
 * and focus, and Alt+T moves focus to the stack. It sits on surface-3 like every
 * other floating layer, and each kind has an icon, so a toast never relies on colour.
 */
function Toaster(props: ToasterProps) {
  const { resolvedTheme } = useTheme()

  return (
    <Sonner
      theme={resolvedTheme === "dark" ? "dark" : "light"}
      className="toaster group"
      icons={{
        success: <CircleCheck aria-hidden="true" className="size-4 text-status-ok" />,
        info: <Info aria-hidden="true" className="size-4 text-status-running" />,
        warning: <TriangleAlert aria-hidden="true" className="size-4 text-status-nit" />,
        error: <CircleX aria-hidden="true" className="size-4 text-status-blocking" />,
        loading: (
          <LoaderCircle
            aria-hidden="true"
            className="size-4 animate-spin text-fg-secondary motion-reduce:animate-none"
          />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--surface-3)",
          "--normal-text": "var(--text-primary)",
          "--normal-border": "var(--border-default)",
          "--border-radius": "12px",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "font-sans text-control shadow-popover!",
          description: "text-fg-secondary!",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
