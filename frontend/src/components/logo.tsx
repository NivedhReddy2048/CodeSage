import Image from "next/image";

import { cn } from "@/lib/utils";

/**
 * The CodeSage mark, with the wordmark beside it unless `markOnly`. The image is
 * decorative whenever the word "CodeSage" is next to it, so a screen reader hears
 * the name once; on its own it carries the name as its alt text.
 */
export function Logo({
  size = 28,
  markOnly = false,
  priority = false,
  className,
  wordmarkClassName,
}: {
  size?: number;
  markOnly?: boolean;
  priority?: boolean;
  className?: string;
  wordmarkClassName?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2.5", className)}>
      <Image
        src="/codesage-logo.png"
        alt={markOnly ? "CodeSage" : ""}
        width={size}
        height={size}
        priority={priority}
        className="shrink-0 rounded-[22%] ring-1 ring-border-brand"
      />
      {markOnly ? null : (
        <span className={cn("truncate text-[0.9375rem] font-semibold tracking-[-0.01em] text-fg", wordmarkClassName)}>
          CodeSage
        </span>
      )}
    </span>
  );
}
