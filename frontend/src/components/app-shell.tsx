"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { CommandPalette } from "@/components/command-palette";
import { Logo } from "@/components/logo";
import { OrganizationProvider, useOrganization } from "@/components/organization-provider";
import { NotificationBell } from "@/components/notification-bell";
import { ErrorState, ListSkeleton } from "@/components/states";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";

/** True for Ctrl+K, and Cmd+K on macOS. */
export function isPaletteShortcut(event: KeyboardEvent) {
  return event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey);
}

function Content({ children }: { children: React.ReactNode }) {
  const { version } = useOrganization();
  // Keyed on the switcher's version: changing organisation remounts the page, so
  // every page reloads its data for the new workspace without each one listening.
  return <div key={version}>{children}</div>;
}

/**
 * Everything behind sign-in: sidebar, top bar, command palette, and the auth guard
 * that every page used to repeat for itself.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, loading, error, reload } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    // Only a rejected session goes to login; an unreachable API keeps it.
    if (!loading && !user && !error) router.replace("/login");
  }, [loading, user, error, router]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isPaletteShortcut(event)) {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  if (!loading && !user && error) {
    return (
      <div className="mx-auto w-full max-w-md px-4 py-24">
        <ErrorState
          title="Could not reach CodeSage"
          message={`${error} You are still signed in.`}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !user) {
    return (
      <div className="mx-auto w-full max-w-md px-4 py-24">
        <ListSkeleton rows={3} label="Signing you in" />
      </div>
    );
  }

  return (
    <OrganizationProvider>
      <SidebarProvider>
        <a
          href="#content"
          className="sr-only z-50 rounded-lg bg-surface-3 px-3 py-2 font-medium text-fg shadow-popover focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>
        <AppSidebar />
        <SidebarInset>
          {/* Glass over the page as it scrolls under. z-20 keeps it above page
              content; menus and dialogs portal out at z-50. */}
          <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border-subtle bg-glass px-3 backdrop-blur-md sm:px-4">
            <SidebarTrigger aria-label="Toggle sidebar" />
            {/* On a phone the sidebar is a drawer, so the mark lives up here. */}
            <Logo markOnly size={24} className="md:hidden" />
            <Separator orientation="vertical" className="mx-1 hidden h-4 md:block" />
            <Button
              variant="outline"
              className="h-8 min-w-0 max-w-md flex-1 justify-start gap-2 bg-surface-1 font-normal text-fg-secondary hover:text-fg dark:bg-surface-1"
              onClick={() => setPaletteOpen(true)}
              aria-keyshortcuts="Control+K Meta+K"
            >
              <Search aria-hidden="true" className="size-4" />
              <span className="flex-1 truncate text-left">Search or jump to...</span>
              <Kbd className="hidden sm:inline-flex">Ctrl K</Kbd>
            </Button>
            <div className="ml-auto flex items-center gap-0.5">
              <NotificationBell />
              <ThemeToggle />
            </div>
          </header>
          {/* min-w-0: a flex child defaults to min-width auto, so a wide table widened
              the whole page on a phone instead of scrolling inside its card. */}
          <main
            id="content"
            tabIndex={-1}
            className="mx-auto w-full min-w-0 max-w-[1380px] flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-8"
          >
            <Content>{children}</Content>
          </main>
        </SidebarInset>
        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
        <Toaster position="bottom-right" />
      </SidebarProvider>
    </OrganizationProvider>
  );
}
