import * as React from "react"

import { cn } from "@/lib/utils"

/** A keycap: mono, tabular, on the surface it sits on. */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center gap-0.5 rounded-[5px] border border-border bg-surface-1 px-1.5 font-mono text-[0.6875rem] font-medium text-fg-secondary tabular-nums shadow-[inset_0_-1px_0_var(--border-default)]",
        className
      )}
      {...props}
    />
  )
}

export { Kbd }
