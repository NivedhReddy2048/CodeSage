import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * One choice out of a few, shown side by side. Built from a fieldset of real radio
 * inputs, so arrow keys move the choice, Tab enters and leaves the group once, and a
 * screen reader hears "Period, group - Last 7 days, radio button, 1 of 3". The
 * chosen segment is told apart by fill, text colour and weight together, never by
 * a fill alone.
 */
function SegmentedControl<T extends string>({
  legend,
  name,
  value,
  options,
  onValueChange,
  hideLegend = false,
  className,
}: {
  legend: string
  name: string
  value: T
  options: readonly { value: T; label: React.ReactNode }[]
  onValueChange: (value: T) => void
  /** Keeps the legend for assistive tech only, when a visible label is redundant. */
  hideLegend?: boolean
  className?: string
}) {
  return (
    <fieldset data-slot="segmented-control" className={cn("min-w-0", className)}>
      <legend
        className={cn(
          "mb-1 text-micro text-fg-secondary",
          hideLegend && "sr-only"
        )}
      >
        {legend}
      </legend>
      <div className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-lg border border-input bg-surface-2 p-0.5">
        {options.map((option) => {
          const checked = option.value === value
          return (
            <label
              key={option.value}
              data-checked={checked || undefined}
              className={cn(
                "inline-flex h-7 cursor-pointer items-center rounded-md px-3 text-control whitespace-nowrap text-fg-secondary transition-colors duration-150 select-none hover:text-fg",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
                "data-checked:bg-surface-1 data-checked:font-medium data-checked:text-brand data-checked:shadow-card data-checked:ring-1 data-checked:ring-border-brand dark:data-checked:bg-surface-3"
              )}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                className="sr-only"
                checked={checked}
                onChange={() => onValueChange(option.value)}
              />
              {option.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

export { SegmentedControl }
