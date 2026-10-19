import { render, screen, waitFor } from "@testing-library/react";
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
