import { ChevronDown } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * A styled native <select>, for filters. Native rather than a custom listbox, so it
 * keeps the platform's keyboard handling, its mobile picker and its `combobox` role
 * and label wiring untouched; only the box around it is ours. The chevron is
 * decorative and ignores the pointer, so a click anywhere opens the select.
 */
function NativeSelect({
  className,
  wrapperClassName,
  ...props
}: React.ComponentProps<"select"> & { wrapperClassName?: string }) {
  return (
    <span
      data-slot="native-select-wrapper"
      className={cn("relative flex min-w-0", wrapperClassName)}
    >
      <select
        data-slot="native-select"
        className={cn(
          "h-8 w-full min-w-0 cursor-pointer appearance-none truncate rounded-lg border border-input bg-surface-2 py-1 pr-8 pl-2.5 text-control text-fg transition-colors hover:bg-[color-mix(in_srgb,var(--surface-2),var(--text-primary)_4%)] focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      />
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-fg-secondary"
      />
    </span>
  )
}

export { NativeSelect }
