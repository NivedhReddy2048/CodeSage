import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { nextNavigationMock, organizations, resetNavigation, user } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({
  organizations: vi.fn(),
  members: vi.fn(),
  updateMemberRole: vi.fn(),
  auditLog: vi.fn(),
  ingestionStatus: vi.fn(),
  reindexRepository: vi.fn(),
  reviews: vi.fn(),
  repositories: vi.fn(),
  review: vi.fn(),
  reviewDiff: vi.fn(),
  reviewStatus: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user, loading: false, signOut: vi.fn(), reload: vi.fn() }),
}));

import AuditLogPage from "@/app/(app)/audit/page";
import SettingsPage from "@/app/(app)/settings/page";
import { IngestionStatus } from "@/components/ingestion-status";
import { OrganizationProvider } from "@/components/organization-provider";
import { Toaster } from "@/components/ui/sonner";
import { ApiError } from "@/lib/api";

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class">
      <OrganizationProvider>{children}</OrganizationProvider>
    </ThemeProvider>
  );
}

const members = [
  { id: 1, role: "owner", created_at: "", user },
  { id: 2, role: "member", created_at: "", user: { ...user, id: 2, github_login: "carol" } },
];

beforeEach(() => {
  resetNavigation();
  apiMock.organizations.mockResolvedValue(organizations);
  apiMock.members.mockResolvedValue(members);
});

describe("settings", () => {
  it("an owner gets a role control per member, and a change is saved", async () => {
    apiMock.updateMemberRole.mockResolvedValue({});
    render(<SettingsPage />, { wrapper: Providers });

    const carol = await screen.findByRole("combobox", { name: "Role for carol" });
    await userEvent.selectOptions(carol, "admin");

    expect(apiMock.updateMemberRole).toHaveBeenCalledWith(2, "admin");
    await waitFor(() => expect(apiMock.members).toHaveBeenCalledTimes(2));
  });

  it("confirms a role change with a toast", async () => {
    apiMock.updateMemberRole.mockResolvedValue({});
    render(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { wrapper: Providers },
    );

    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Role for carol" }), "admin");

    expect(await screen.findByText("carol is now an admin")).toBeInTheDocument();
  });

  it("a member sees roles but cannot change them", async () => {
    window.localStorage.setItem("codesage.organization", "20"); // acme, role member
    render(<SettingsPage />, { wrapper: Providers });

    expect(await screen.findByText("carol")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("the server's refusal is shown, not swallowed", async () => {
    apiMock.updateMemberRole.mockRejectedValue(
      new ApiError(400, "An organisation must keep at least one owner."),
    );
    render(<SettingsPage />, { wrapper: Providers });

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: "Role for alice" }),
      "member",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("at least one owner");
  });

  it("offers light, dark and system themes", async () => {
    render(<SettingsPage />, { wrapper: Providers });

    for (const name of ["Light", "Dark", "System"]) {
      expect(screen.getByRole("radio", { name })).toBeInTheDocument();
    }
  });
});

describe("audit log", () => {
  it("a 403 reads as 'owners and admins only', not as a failure", async () => {
    apiMock.auditLog.mockRejectedValue(new ApiError(403, "Forbidden"));
    render(<AuditLogPage />, { wrapper: Providers });

    expect(await screen.findByText("Owners and admins only")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("other failures are errors with a retry", async () => {
    apiMock.auditLog.mockRejectedValueOnce(new ApiError(0, "Could not reach the API."));
    apiMock.auditLog.mockResolvedValueOnce({ count: 0, next: null, previous: null, results: [] });
    render(<AuditLogPage />, { wrapper: Providers });

    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Nothing recorded yet")).toBeInTheDocument();
  });

  it("lists entries", async () => {
    apiMock.auditLog.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          action: "repo.connected",
          action_label: "Repository connected",
          actor_login: "alice",
          target_type: "repository",
          target_id: "7",
          target_label: "alice/app",
          metadata: {},
          created_at: "2026-10-19T10:00:00Z",
        },
      ],
    });
    render(<AuditLogPage />, { wrapper: Providers });

    expect(await screen.findByText("Repository connected")).toBeInTheDocument();
    expect(screen.getByText("alice/app")).toBeInTheDocument();
  });
});

describe("indexing status", () => {
  const failed = (error: string, canManage: boolean) => ({
    chunk_count: 0,
    indexed_files: 0,
    can_manage: canManage,
    job: {
      id: 1,
      status: "failed",
      is_active: false,
      error,
      error_summary: "The embedding provider was unavailable",
    },
  });

  it("a member sees the short reason and no re-index button", async () => {
    apiMock.ingestionStatus.mockResolvedValue(failed("", false));
    render(<IngestionStatus repositoryId={7} />);

    expect(await screen.findByText(/embedding provider was unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("Details")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-index" })).not.toBeInTheDocument();
  });

  it("an owner can expand the raw error and re-index", async () => {
    apiMock.ingestionStatus.mockResolvedValue(failed("HTTP 429: RESOURCE_EXHAUSTED", true));
    render(<IngestionStatus repositoryId={7} />);

    expect(await screen.findByText("Details")).toBeInTheDocument();
    expect(screen.getByText("HTTP 429: RESOURCE_EXHAUSTED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeInTheDocument();
  });
});

describe("reviews list filters", () => {
  it("live in the URL, so a filtered view can be bookmarked", async () => {
    const { navigation } = await import("@/test/mocks");
    const { default: ReviewsPage } = await import("@/app/(app)/reviews/page");
    apiMock.reviews.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    apiMock.repositories.mockResolvedValue([{ id: 7, full_name: "alice/app" }]);
    navigation.search = new URLSearchParams("repository=7");
    render(<ReviewsPage />, { wrapper: Providers });

    await userEvent.selectOptions(await screen.findByLabelText("Status"), "degraded");

    expect(navigation.push).toHaveBeenCalledWith("/reviews?repository=7&status=degraded");
    expect(apiMock.reviews).toHaveBeenCalledWith(
      expect.objectContaining({ repository: "7", page: 1 }),
    );
    expect(await screen.findByText("No reviews match these filters")).toBeInTheDocument();
  });

  it("counts the active filters and clears them all at once", async () => {
    const { navigation } = await import("@/test/mocks");
    const { default: ReviewsPage } = await import("@/app/(app)/reviews/page");
    apiMock.reviews.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    apiMock.repositories.mockResolvedValue([{ id: 7, full_name: "alice/app" }]);
    navigation.search = new URLSearchParams("repository=7&severity=blocking");
    render(<ReviewsPage />, { wrapper: Providers });

    const toolbar = await screen.findByRole("form", { name: "Filter reviews" });
    expect(within(toolbar).getByText("2 active")).toBeInTheDocument();

    await userEvent.click(within(toolbar).getByRole("button", { name: "Clear filters" }));
    expect(navigation.push).toHaveBeenLastCalledWith("/reviews");
  });
});

describe("review detail", () => {
  const review = {
    id: 31,
    repository: "alice/app",
    repository_id: 7,
    pr_number: 3,
    pr_title: "Lookup",
    pr_url: "https://github.com/alice/app/pull/3",
    can_manage: false,
    status: "done",
    head_sha: "76fb4bd0",
    model_used: "openai/gpt-oss-120b",
    used_fallback: false,
    total_input_tokens: 10,
    total_output_tokens: 5,
    duration_ms: 3600,
    estimated_cost_usd: "0",
    estimated_cost_inr: "0.0725",
    degraded: false,
    truncated: false,
    skipped_files: [],
    error: "",
    error_summary: "",
    progress: {},
    created_at: "",
    started_at: null,
    finished_at: null,
    findings: [],
    calls: [],
    agent_runs: [],
  };

  async function renderReview(overrides: Record<string, unknown>, orgId?: string) {
    const { navigation } = await import("@/test/mocks");
    const { default: ReviewPage } = await import("@/app/(app)/reviews/[id]/page");
    navigation.params = { id: "31" };
    if (orgId) window.localStorage.setItem("codesage.organization", orgId);
    apiMock.review.mockResolvedValue({ ...review, ...overrides });
    apiMock.reviewDiff.mockResolvedValue({ diff: "", source: "stored", truncated: false, head_sha: "" });
    render(<ReviewPage />, { wrapper: Providers });
    await screen.findByRole("heading", { name: "alice/app#3" });
  }

  it("a member gets no re-run button", async () => {
    await renderReview({ can_manage: false }, "20");
    expect(screen.queryByRole("button", { name: "Re-run review" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Pull request on GitHub/ })).toHaveAttribute(
      "href",
      "https://github.com/alice/app/pull/3",
    );
  });

  it("an owner gets one", async () => {
    await renderReview({ can_manage: true });
    expect(await screen.findByRole("button", { name: "Re-run review" })).toBeInTheDocument();
  });

  it("a degraded review says so, with the short reason only", async () => {
    await renderReview({
      status: "failed",
      degraded: true,
      error_summary: "AI providers unavailable",
    });
    expect(screen.getByRole("alert")).toHaveTextContent("AI providers unavailable");
    expect(screen.queryByText(/Error details/)).not.toBeInTheDocument();
  });

  it("explains a fallback in a callout, without alarming", async () => {
    await renderReview({ used_fallback: true });
    expect(screen.getByText("Answered by the fallback provider")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("labels the cost as an estimate, at two decimals with the exact figure on hover", async () => {
    await renderReview({});
    expect(screen.getByText("Est. cost at paid-tier rates")).toBeInTheDocument();
    expect(screen.getByText("₹0.07")).toHaveAttribute("title", "Exact estimate: ₹0.0725");
  });

  it("says how many findings, and how many block, in words", async () => {
    const finding = (id: number, severity: "blocking" | "nit") => ({
      id,
      agent: "security",
      severity,
      category: "security",
      file_path: "app/x.py",
      line: id,
      placement: "inline",
      message: "m",
      citation: "",
      dismissed: false,
    });
    await renderReview({ findings: [finding(1, "blocking")] });
    expect(screen.getByText(/1 finding/)).toHaveTextContent("1 finding · 1 blocking");
  });

  it("lists every model instead of cutting the names off, and tags a re-run", async () => {
    await renderReview({ model_used: "openai/gpt-oss-120b, openai/gpt-oss-20b", trigger: "rerun" });
    expect(screen.getByText("openai/gpt-oss-120b")).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-oss-20b")).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-oss-20b").closest("dd")).not.toHaveClass("truncate");
    expect(screen.getByText("Re-run")).toBeInTheDocument();
  });
});
