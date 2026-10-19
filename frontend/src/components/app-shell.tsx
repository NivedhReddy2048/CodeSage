"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { CommandPalette } from "@/components/command-palette";
import { OrganizationProvider, useOrganization } from "@/components/organization-provider";
import { ErrorState, ListSkeleton } from "@/components/states";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

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
          className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>
        <AppSidebar />
        <SidebarInset>
          <header className="sticky top-0 z-10 flex h-14 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur">
            <SidebarTrigger aria-label="Toggle sidebar" />
            <Separator orientation="vertical" className="mr-1 h-4" />
            <Button
              variant="outline"
              className="h-8 min-w-0 max-w-sm flex-1 justify-start gap-2 text-muted-foreground"
              onClick={() => setPaletteOpen(true)}
              aria-keyshortcuts="Control+K Meta+K"
            >
              <Search aria-hidden="true" className="size-4" />
              <span className="flex-1 truncate text-left">Search or jump to...</span>
              <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">
                Ctrl K
              </kbd>
            </Button>
            <div className="ml-auto flex items-center gap-1">
              <ThemeToggle />
            </div>
          </header>
          {/* min-w-0: a flex child defaults to min-width auto, so a wide table widened
              the whole page on a phone instead of scrolling inside its card. */}
          <main
            id="content"
            tabIndex={-1}
            className="mx-auto w-full min-w-0 max-w-6xl flex-1 px-4 py-8 outline-none sm:px-6"
          >
            <Content>{children}</Content>
          </main>
        </SidebarInset>
        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      </SidebarProvider>
    </OrganizationProvider>
  );
}
