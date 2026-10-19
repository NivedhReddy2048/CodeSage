import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { navigation, nextNavigationMock, organizations, resetNavigation, user } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({
  organizations: vi.fn(),
  repositories: vi.fn(),
  reviews: vi.fn(),
  currentUser: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));

const auth = vi.hoisted(() => ({ signOut: vi.fn() }));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user, loading: false, signOut: auth.signOut, reload: vi.fn() }),
}));

import { AppSidebar, isActivePath } from "@/components/app-sidebar";
import { isPaletteShortcut } from "@/components/app-shell";
import { CommandPalette } from "@/components/command-palette";
import { OrganizationProvider, useOrganization } from "@/components/organization-provider";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class">
      <TooltipProvider>
        <OrganizationProvider>
          <SidebarProvider>{children}</SidebarProvider>
        </OrganizationProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}

beforeEach(() => {
  resetNavigation();
  apiMock.organizations.mockResolvedValue(organizations);
  apiMock.repositories.mockResolvedValue([
    { id: 7, full_name: "alice/app", private: false, default_branch: "main" },
  ]);
  apiMock.reviews.mockResolvedValue({
    count: 1,
    next: null,
    previous: null,
    results: [{ id: 31, repository: "alice/app", pr_number: 3, pr_title: "Lookup" }],
  });
});

describe("navigation", () => {
  it("matches the dashboard exactly and sections by prefix", () => {
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/reviews", "/")).toBe(false);
    expect(isActivePath("/reviews/31", "/reviews")).toBe(true);
    expect(isActivePath("/repos", "/reviews")).toBe(false);
  });

  it("lists every section and marks the current one for assistive tech", async () => {
    navigation.pathname = "/reviews/31";
    render(<AppSidebar />, { wrapper: Providers });

    const nav = screen.getByRole("navigation", { name: "Primary" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Dashboard",
      "Repositories",
      "Reviews",
      "Audit log",
      "Settings",
    ]);
    expect(within(nav).getByRole("link", { name: "Reviews" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });
});

describe("organisation switcher", () => {
  function Probe() {
    const { current, version, switchTo, canManage } = useOrganization();
    return (
      <div>
        <span data-testid="current">{current?.name ?? "none"}</span>
        <span data-testid="version">{version}</span>
        <span data-testid="manage">{String(canManage)}</span>
        <button onClick={() => switchTo(20)}>switch</button>
      </div>
    );
  }

  it("defaults to the personal organisation the user owns", async () => {
    render(<Probe />, { wrapper: Providers });

    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("alice"));
    expect(screen.getByTestId("manage")).toHaveTextContent("true");
  });

  it("restores a stored choice the user still belongs to", async () => {
    window.localStorage.setItem("codesage.organization", "20");
    render(<Probe />, { wrapper: Providers });

    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("acme"));
    expect(screen.getByTestId("manage")).toHaveTextContent("false");
  });

  it("ignores a stored organisation the user is not in", async () => {
    window.localStorage.setItem("codesage.organization", "999");
    render(<Probe />, { wrapper: Providers });

    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("alice"));
  });

  it("switching stores the choice and bumps the version that remounts pages", async () => {
    render(<Probe />, { wrapper: Providers });
    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("alice"));

    await userEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(screen.getByTestId("current")).toHaveTextContent("acme");
    expect(screen.getByTestId("version")).toHaveTextContent("1");
    expect(window.localStorage.getItem("codesage.organization")).toBe("20");
  });
});

describe("command palette", () => {
  it("opens on Ctrl+K and Cmd+K only", () => {
    const key = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);
    expect(isPaletteShortcut(key({ key: "k", ctrlKey: true }))).toBe(true);
    expect(isPaletteShortcut(key({ key: "K", metaKey: true }))).toBe(true);
    expect(isPaletteShortcut(key({ key: "k" }))).toBe(false);
    expect(isPaletteShortcut(key({ key: "j", ctrlKey: true }))).toBe(false);
  });

  it("is a labelled dialog listing pages, repositories and recent reviews", async () => {
    render(<CommandPalette open onOpenChange={() => undefined} />, { wrapper: Providers });

    const dialog = await screen.findByRole("dialog", { name: "Command palette" });
    expect(within(dialog).getByText("Audit log")).toBeInTheDocument();
    expect(await within(dialog).findByText("alice/app")).toBeInTheDocument();
    expect(within(dialog).getByText(/alice\/app#3/)).toBeInTheDocument();
  });

  it("jumps to a review and closes", async () => {
    const onOpenChange = vi.fn();
    render(<CommandPalette open onOpenChange={onOpenChange} />, { wrapper: Providers });

    await userEvent.click(await screen.findByText(/alice\/app#3/));

    expect(navigation.push).toHaveBeenCalledWith("/reviews/31");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("filters as you type", async () => {
    render(<CommandPalette open onOpenChange={() => undefined} />, { wrapper: Providers });
    await screen.findByText("alice/app");

    await userEvent.type(screen.getByPlaceholderText(/Search pages/), "settings");

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.queryByText("Audit log")).not.toBeInTheDocument();
  });

  it("still offers pages when repositories cannot load", async () => {
    apiMock.repositories.mockRejectedValue(new Error("down"));
    render(<CommandPalette open onOpenChange={() => undefined} />, { wrapper: Providers });

    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });
});
