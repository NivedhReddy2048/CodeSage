import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("rounded-md bg-surface-2 motion-safe:animate-pulse dark:bg-surface-3", className)}
      {...props}
    />
  )
}

export { Skeleton }
