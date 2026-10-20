"use client";

import { FolderGit2, GitPullRequest, LogOut } from "lucide-react";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { NAV_ITEMS } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { THEME_OPTIONS } from "@/components/theme-toggle";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { api } from "@/lib/api";
import type { ConnectedRepository, ReviewListItem } from "@/lib/types";

type Data = { repos: ConnectedRepository[]; reviews: ReviewListItem[] };

/**
 * Ctrl/Cmd+K: jump to any page, repository or recent review, or run an action.
 * Repositories and reviews load when the palette opens rather than on every page,
 * and a failure to load them leaves the pages and actions usable.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const { setTheme } = useTheme();
  const { signOut } = useAuth();
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    Promise.all([api.repositories(), api.reviews({ page_size: 10 })])
      .then(([repos, reviews]) => {
        if (active) setData({ repos, reviews: reviews.results });
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [open]);

  function run(action: () => void) {
    onOpenChange(false);
    action();
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Command palette"
      description="Jump to a page, repository or review, or run an action."
    >
      {/* This shadcn version leaves the cmdk root to the caller; without it the
          input and list have no store and the palette crashes on open. */}
      <Command>
        <CommandInput placeholder="Search pages, repositories, reviews..." />
        <CommandList>
          <CommandEmpty>No matches.</CommandEmpty>

          <CommandGroup heading="Pages">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
              <CommandItem key={href} value={`page ${label}`} onSelect={() => run(() => router.push(href))}>
                <Icon aria-hidden="true" />
                {label}
              </CommandItem>
            ))}
          </CommandGroup>

          {data && data.repos.length > 0 ? (
            <CommandGroup heading="Repositories">
              {data.repos.map((repo) => (
                <CommandItem
                  key={repo.id}
                  value={`repository ${repo.full_name}`}
                  onSelect={() => run(() => router.push(`/reviews?repository=${repo.id}`))}
                >
                  <FolderGit2 aria-hidden="true" />
                  <span className="truncate font-mono text-[0.8125rem]">{repo.full_name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}

          {data && data.reviews.length > 0 ? (
            <CommandGroup heading="Recent reviews">
              {data.reviews.map((review) => (
                <CommandItem
                  key={review.id}
                  value={`review ${review.repository} ${review.pr_number} ${review.pr_title}`}
                  onSelect={() => run(() => router.push(`/reviews/${review.id}`))}
                >
                  <GitPullRequest aria-hidden="true" />
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 font-mono text-[0.8125rem] tabular-nums">
                      {review.repository}#{review.pr_number}
                    </span>
                    <span className="truncate text-fg-secondary">{review.pr_title}</span>
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}

          {failed ? (
            <p className="px-2.5 py-2 text-xs text-fg-secondary">
              Repositories and reviews could not be loaded.
            </p>
          ) : null}

          <CommandSeparator />
          <CommandGroup heading="Actions">
            {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
              <CommandItem key={value} value={`theme ${label}`} onSelect={() => run(() => setTheme(value))}>
                <Icon aria-hidden="true" />
                Theme: {label}
              </CommandItem>
            ))}
            <CommandItem value="sign out" onSelect={() => run(signOut)}>
              <LogOut aria-hidden="true" />
              Sign out
            </CommandItem>
          </CommandGroup>
        </CommandList>
        {/* How to drive it, for anyone who opened it with the mouse. */}
        <div
          aria-hidden="true"
          className="flex items-center gap-4 border-t bg-surface-2/60 px-4 py-2 text-xs text-fg-secondary"
        >
          <span className="flex items-center gap-1.5">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd>
            Navigate
          </span>
          <span className="flex items-center gap-1.5">
            <Kbd>↵</Kbd>
            Open
          </span>
          <span className="ml-auto flex items-center gap-1.5">
            <Kbd>Esc</Kbd>
            Close
          </span>
        </div>
      </Command>
    </CommandDialog>
  );
}
