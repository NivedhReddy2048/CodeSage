import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { navigation, nextNavigationMock, organizations, resetNavigation, user } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({
  organizations: vi.fn(),
  analytics: vi.fn(),
  reviews: vi.fn(),
  repositories: vi.fn(),
  notifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  auditLog: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user, loading: false, error: null, signOut: vi.fn(), reload: vi.fn() }),
}));

import AuditLogPage from "@/app/(app)/audit/page";
import DashboardPage from "@/app/(app)/page";
import { NotificationBell } from "@/components/notification-bell";
import { OrganizationProvider } from "@/components/organization-provider";
import { ApiError } from "@/lib/api";
import type { AnalyticsOverview } from "@/lib/types";

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class">
      <OrganizationProvider>{children}</OrganizationProvider>
    </ThemeProvider>
  );
}

const overview: AnalyticsOverview = {
  range: { days: 30, since: "", until: "" },
  cost_basis: "Estimated at paid-tier rates. CodeSage runs on free tiers, so actual spend is zero.",
  summary: {
    prs_reviewed: 3,
    reviews: 27,
    completed_reviews: 23,
    degraded_reviews: 1,
    failed_reviews: 3,
    fallback_reviews: 1,
    findings: 35,
    blocking: 24,
    nits: 11,
    blocking_ratio: 0.686,
    avg_findings_per_pr: 1.67,
    avg_latency_ms: 4623,
    est_cost_inr_total: "1.7506",
    est_cost_inr_avg: "0.0648",
  },
  timeseries: [
    { date: "2026-10-18", reviews: 20, findings: 30, blocking: 20, nits: 10, avg_latency_ms: 5000, est_cost_inr: "1.2" },
    { date: "2026-10-19", reviews: 7, findings: 5, blocking: 4, nits: 1, avg_latency_ms: 4000, est_cost_inr: "0.5" },
  ],
  by_category: [{ key: "correctness", count: 17, blocking: 9 }],
  by_agent: [{ key: "test_coverage", count: 18, blocking: 18 }],
};

const empty = { count: 0, next: null, previous: null, results: [] };

beforeEach(() => {
  resetNavigation();
  apiMock.organizations.mockResolvedValue(organizations);
  apiMock.analytics.mockResolvedValue(overview);
  apiMock.reviews.mockResolvedValue(empty);
  apiMock.repositories.mockResolvedValue([{ id: 7, full_name: "alice/app" }]);
});

describe("dashboard", () => {
  it("leads with the four KPIs, cost labelled as an estimate", async () => {
    render(<DashboardPage />, { wrapper: Providers });

    expect(await screen.findByText("PRs reviewed")).toBeInTheDocument();
    expect(screen.getByText("1.67")).toBeInTheDocument();
    expect(screen.getByText("4.6 s")).toBeInTheDocument();
    expect(screen.getByText("Est. cost per review")).toBeInTheDocument();
    expect(screen.getByText(/At paid-tier rates/)).toHaveTextContent("actual spend ₹0");
  });

  it("splits the review count into done, degraded, failed and in progress", async () => {
    render(<DashboardPage />, { wrapper: Providers });

    const tile = (await screen.findByText("PRs reviewed")).closest("[data-slot=card]") as HTMLElement;
    // 27 reviews: 23 done, 1 degraded, 3 failed - and 0 in progress, so not listed.
    expect(tile).toHaveTextContent("23 done");
    expect(tile).toHaveTextContent("1 degraded");
    expect(tile).toHaveTextContent("3 failed");
    expect(tile).not.toHaveTextContent("in progress");
  });

  it("draws the three charts, each with its table view", async () => {
    render(<DashboardPage />, { wrapper: Providers });

    for (const title of ["Reviews per day", "Findings by category", "Agent contribution"]) {
      expect(await screen.findByText(title)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("button", { name: "Show table" })).toHaveLength(3);
    expect(screen.getByRole("listitem", { name: /Test coverage: 18 findings \(18 blocking, 0 nits\)/ })).toBeInTheDocument();
  });

  it("filters live in one row above everything and in the URL", async () => {
    render(<DashboardPage />, { wrapper: Providers });
    await screen.findByText("PRs reviewed");

    await userEvent.click(screen.getByRole("radio", { name: "Last 7 days" }));
    expect(navigation.push).toHaveBeenCalledWith("/?days=7");

    await userEvent.selectOptions(screen.getByLabelText("Repository"), "7");
    expect(navigation.push).toHaveBeenLastCalledWith("/?repository=7");
  });

  it("reads the period from the URL and scopes the analytics to it", async () => {
    navigation.search = new URLSearchParams("days=90&repository=7");
    render(<DashboardPage />, { wrapper: Providers });

    await waitFor(() => expect(apiMock.analytics).toHaveBeenCalledWith({ days: 90, repository: "7" }));
    expect(screen.getByRole("radio", { name: "Last 90 days" })).toBeChecked();
  });

  it("an empty period says so instead of drawing empty charts", async () => {
    apiMock.analytics.mockResolvedValue({
      ...overview,
      summary: { ...overview.summary, reviews: 0, prs_reviewed: 0 },
      timeseries: [],
      by_category: [],
      by_agent: [],
    });
    render(<DashboardPage />, { wrapper: Providers });

    expect(await screen.findByText("No reviews in this period")).toBeInTheDocument();
    expect(screen.queryByText("Reviews per day")).not.toBeInTheDocument();
  });

  it("an analytics failure is an error with a retry", async () => {
    apiMock.analytics.mockRejectedValueOnce(new ApiError(0, "Could not reach the API."));
    render(<DashboardPage />, { wrapper: Providers });

    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("PRs reviewed")).toBeInTheDocument();
  });
});

describe("notification bell", () => {
  const notes = [
    { id: 1, kind: "review.degraded", title: "Review of alice/app#3 ran in degraded mode", body: "No AI provider answered.", link: "/reviews/3", read: false, read_at: null, created_at: new Date().toISOString() },
    { id: 2, kind: "review.finished", title: "Review of alice/app#2 finished", body: "1 finding.", link: "/reviews/2", read: true, read_at: "", created_at: new Date().toISOString() },
  ];

  it("puts the unread count in the button's accessible name", async () => {
    apiMock.notifications.mockResolvedValue({ unread_count: 1, results: notes });
    render(<NotificationBell />);

    expect(await screen.findByRole("button", { name: "Notifications, 1 unread" })).toBeInTheDocument();
  });

  it("opening one marks it read and links to it", async () => {
    apiMock.notifications.mockResolvedValue({ unread_count: 1, results: notes });
    apiMock.markNotificationRead.mockResolvedValue({});
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    const item = await screen.findByRole("menuitem", { name: /degraded mode/ });
    expect(item).toHaveAttribute("href", "/reviews/3");
    expect(item).toHaveTextContent("(unread)");

    await userEvent.click(item);

    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(1);
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("mark all as read", async () => {
    apiMock.notifications.mockResolvedValue({ unread_count: 1, results: notes });
    apiMock.markAllNotificationsRead.mockResolvedValue({ marked: 1 });
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Mark all as read" }));

    expect(apiMock.markAllNotificationsRead).toHaveBeenCalledOnce();
  });

  it("titles lead with the PR number, keep the full name on hover, and open the review", async () => {
    const note = {
      id: 9,
      kind: "review.finished",
      title: "codesage-testbed #7 · 1 blocking",
      body: "Review finished.",
      link: "/reviews/44",
      meta: { repository: "NivedhReddy2048/codesage-testbed", pr_number: 7, head_sha: "7693464abc", trigger: "rerun" },
      read: false,
      read_at: null,
      created_at: new Date().toISOString(),
    };
    apiMock.notifications.mockResolvedValue({ unread_count: 1, results: [note] });
    apiMock.markNotificationRead.mockResolvedValue({});
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    const item = await screen.findByRole("menuitem", { name: /codesage-testbed #7/ });
    expect(within(item).getByText("codesage-testbed #7 · 1 blocking")).toHaveAttribute(
      "title",
      "NivedhReddy2048/codesage-testbed #7 · 1 blocking",
    );
    expect(within(item).getByText("7693464")).toBeInTheDocument();
    expect(within(item).getByText("Re-run")).toBeInTheDocument();
    expect(item).toHaveAttribute("href", "/reviews/44");

    await userEvent.click(item);
    expect(apiMock.markNotificationRead).toHaveBeenCalledWith(9);
  });

  it("caps the visible count, and keeps the pill out of the accessible name", async () => {
    apiMock.notifications.mockResolvedValue({ unread_count: 12, results: notes });
    render(<NotificationBell />);

    const bell = await screen.findByRole("button", { name: "Notifications, 12 unread" });
    expect(within(bell).getByText("9+")).toHaveAttribute("aria-hidden", "true");
  });

  it("an empty bell says so", async () => {
    apiMock.notifications.mockResolvedValue({ unread_count: 0, results: [] });
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("You are all caught up.")).toBeInTheDocument();
  });
});

describe("audit log filters", () => {
  it("apply together, into the URL, and reach the API", async () => {
    apiMock.auditLog.mockResolvedValue(empty);
    render(<AuditLogPage />, { wrapper: Providers });

    const form = await screen.findByRole("form", { name: "Filter the audit log" });
    await userEvent.selectOptions(within(form).getByLabelText("Action"), "review.rerun");
    await userEvent.type(within(form).getByLabelText("Actor"), "alice");
    // Nothing fetched per keystroke.
    expect(navigation.push).not.toHaveBeenCalled();
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));

    expect(navigation.push).toHaveBeenCalledWith("/audit?action=review.rerun&actor=alice");
  });

  it("filters from the URL are sent with the page size", async () => {
    apiMock.auditLog.mockResolvedValue(empty);
    navigation.search = new URLSearchParams("since=2026-10-01&page=2");
    render(<AuditLogPage />, { wrapper: Providers });

    await waitFor(() =>
      expect(apiMock.auditLog).toHaveBeenCalledWith(
        expect.objectContaining({ since: "2026-10-01", page: 2, page_size: 25 }),
      ),
    );
    expect(await screen.findByText("No entries match these filters")).toBeInTheDocument();
  });
});
