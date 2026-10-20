import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariantsBase = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-control font-medium whitespace-nowrap transition-[color,background-color,border-color,box-shadow,transform] duration-150 ease-standard select-none motion-safe:active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-xs hover:bg-brand-hover aria-expanded:bg-brand-hover",
        outline:
          "border-border bg-surface-1 text-fg hover:border-border-strong hover:bg-surface-2 aria-expanded:bg-surface-2 dark:border-border-strong dark:bg-surface-2 dark:hover:bg-accent",
        secondary:
          "bg-surface-2 text-fg hover:bg-[color-mix(in_srgb,var(--surface-2),var(--text-primary)_6%)] aria-expanded:bg-[color-mix(in_srgb,var(--surface-2),var(--text-primary)_6%)]",
        ghost:
          "text-fg-secondary hover:bg-surface-2 hover:text-fg aria-expanded:bg-surface-2 aria-expanded:text-fg dark:hover:bg-accent dark:aria-expanded:bg-accent",
        destructive:
          "border-status-blocking-border bg-status-blocking-bg text-status-blocking hover:bg-[color-mix(in_srgb,var(--status-blocking-bg),var(--status-blocking)_10%)]",
        link: "text-brand underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

/**
 * Merged, like <Button> itself. The raw cva string carries both `border-transparent`
 * and the variant's border colour, and without merging the transparent one won -
 * so a link styled as an outline button rendered with no border at all.
 */
function buttonVariants(props?: Parameters<typeof buttonVariantsBase>[0]) {
  return cn(buttonVariantsBase(props))
}

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariantsBase>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariantsBase({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
