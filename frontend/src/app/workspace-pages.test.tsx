import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { nextNavigationMock, organizations, resetNavigation, user } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({
  organizations: vi.fn(),
  members: vi.fn(),
  repositories: vi.fn(),
  installableRepositories: vi.fn(),
  connectRepository: vi.fn(),
  disconnectRepository: vi.fn(),
  ingestionStatus: vi.fn(),
  reindexRepository: vi.fn(),
  auditLog: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user, loading: false, signOut: vi.fn(), reload: vi.fn() }),
}));

import AuditLogPage from "@/app/(app)/audit/page";
import ReposPage from "@/app/(app)/repos/page";
import SettingsPage from "@/app/(app)/settings/page";
import { IngestionStatus } from "@/components/ingestion-status";
import { OrganizationProvider } from "@/components/organization-provider";
import { EmptyState } from "@/components/states";
import { Toaster } from "@/components/ui/sonner";

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class">
      <OrganizationProvider>
        {children}
        <Toaster />
      </OrganizationProvider>
    </ThemeProvider>
  );
}

const repo = {
  id: 7,
  github_id: 70,
  full_name: "acme/payments-api",
  owner: "acme",
  name: "payments-api",
  default_branch: "main",
  private: true,
  installation_id: 1,
  connected_by_login: "alice",
  created_at: "",
};

const doneJob = {
  id: 1,
  status: "done",
  is_active: false,
  commit_sha: "abc1234def",
  files_discovered: 42,
  files_indexed: 40,
  files_skipped: 2,
  chunks_created: 120,
  chunks_reused: 80,
  embedding_api_calls: 3,
  error: "",
  error_summary: "",
};

beforeEach(() => {
  resetNavigation();
  apiMock.organizations.mockResolvedValue(organizations);
  apiMock.ingestionStatus.mockResolvedValue({ job: doneJob, chunk_count: 200, indexed_files: 40, can_manage: true });
});

describe("repositories page", () => {
  beforeEach(() => {
    apiMock.repositories.mockResolvedValue([repo]);
    apiMock.installableRepositories.mockResolvedValue({
      installed: true,
      install_url: "https://github.com/apps/codesage/installations/new",
      repositories: [{ ...repo, github_id: 71, full_name: "acme/web", private: false, connected: false }],
    });
  });

  it("shows a connected repository as a card: owner/repo, visibility, branch, index health", async () => {
    render(<ReposPage />, { wrapper: Providers });

    const connected = await screen.findByRole("region", { name: /Connected/ });
    const card = within(connected).getByRole("listitem");
    expect(within(card).getByRole("link")).toHaveTextContent("acme/payments-api");
    expect(within(card).getByText("Private")).toBeInTheDocument();
    expect(within(card).getByText("main")).toBeInTheDocument();
    expect(await within(card).findByText("Indexed")).toBeInTheDocument();
    expect(within(card).getByText(/Last run reused/)).toHaveTextContent(
      "Last run reused 80 of 120 chunk embeddings; 3 embedding calls",
    );
  });

  it("explains indexing as the code does it", async () => {
    render(<ReposPage />, { wrapper: Providers });

    const how = await screen.findByRole("region", { name: "How indexing works" });
    expect(how).toHaveTextContent("Python by its AST");
    expect(how).toHaveTextContent("pgvector");
    expect(how).toHaveTextContent("content hash");
    expect(how).not.toHaveTextContent(/tree-sitter/i);
  });

  it("confirms a connection with a toast", async () => {
    apiMock.connectRepository.mockResolvedValue({});
    render(<ReposPage />, { wrapper: Providers });

    await userEvent.click(await screen.findByRole("button", { name: "Connect" }));

    expect(apiMock.connectRepository).toHaveBeenCalledWith(71);
    expect(await screen.findByText("Connected acme/web; indexing has started")).toBeInTheDocument();
  });
});

describe("index health", () => {
  it("shows files indexed so far while a job runs", async () => {
    apiMock.ingestionStatus.mockResolvedValue({
      job: { ...doneJob, status: "running", is_active: true, files_indexed: 12 },
      chunk_count: 0,
      indexed_files: 0,
      can_manage: false,
    });
    render(<IngestionStatus repositoryId={7} />);

    expect(await screen.findByText("Indexing... 12/42 files")).toBeInTheDocument();
    expect(screen.getByText(/files indexed/)).toHaveTextContent("12 of 42 files indexed");
  });

  it("keeps showing the indexed commit while a re-index runs", async () => {
    apiMock.ingestionStatus.mockResolvedValue({
      job: { ...doneJob, status: "running", is_active: true, commit_sha: "" },
      chunk_count: 200,
      indexed_files: 40,
      can_manage: false,
      last_indexed_commit: "abc1234def",
      last_indexed_at: "2026-10-21T10:00:00Z",
    });
    render(<IngestionStatus repositoryId={7} />);

    const commit = await screen.findByText("abc1234");
    expect(commit).toHaveAttribute("title", "abc1234def (indexed; re-indexing now)");
    expect(commit).toHaveTextContent("re-indexing");
  });
});

describe("audit log", () => {
  it("states its scope and that it is append-only, and pills each action", async () => {
    apiMock.auditLog.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          action: "repo.disconnected",
          action_label: "Repository disconnected",
          actor_login: "alice",
          target_type: "repository",
          target_id: "7",
          target_label: "acme/payments-api",
          metadata: {},
          created_at: "2026-10-19T10:00:00Z",
        },
      ],
    });
    render(<AuditLogPage />, { wrapper: Providers });

    expect(await screen.findByText(/All activity in this organisation/)).toHaveTextContent("1 entry");
    expect(screen.getByText(/Append-only/)).toBeInTheDocument();
    // The action carries its word, not only a colour.
    expect(within(screen.getByRole("table")).getByText("Repository disconnected").closest("span")).toHaveClass(
      "text-status-blocking",
    );
  });

  it("filters to auth events as a group, and pills each one", async () => {
    const { navigation } = await import("@/test/mocks");
    navigation.search = new URLSearchParams("action=auth");
    const entry = (id: number, action: string, action_label: string) => ({
      id,
      action,
      action_label,
      actor_login: "alice",
      target_type: "",
      target_id: "",
      target_label: "alice",
      metadata: { ip: "203.0.113.7" },
      created_at: "2026-10-22T10:00:00Z",
    });
    apiMock.auditLog.mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [entry(1, "auth.signed_in", "Signed in"), entry(2, "auth.sign_in_failed", "Sign-in failed")],
    });
    render(<AuditLogPage />, { wrapper: Providers });

    expect(await screen.findByText("Signed in")).toBeInTheDocument();
    expect(apiMock.auditLog).toHaveBeenCalledWith(expect.objectContaining({ action: "auth" }));
    expect(screen.getByRole("option", { name: "Auth (sign-in, sign-out, failed sign-in)" })).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Sign-in failed").closest("span")).toHaveClass(
      "text-status-blocking",
    );
  });
});

describe("settings", () => {
  it("lists what each role may do, as the API enforces it", async () => {
    apiMock.members.mockResolvedValue([{ id: 1, role: "owner", created_at: "", user }]);
    render(<SettingsPage />, { wrapper: Providers });

    const table = await screen.findByRole("table", { name: "Permissions by role" });
    const roles = within(table).getByRole("row", { name: /Change members' roles/ });
    expect(within(roles).getAllByText("Allowed")).toHaveLength(1);
    expect(within(roles).getAllByText("Not allowed")).toHaveLength(2);

    const reindex = within(table).getByRole("row", { name: /Re-index a repository/ });
    expect(within(reindex).getAllByText("Allowed")).toHaveLength(2);
  });

  it("marks the signed-in member", async () => {
    apiMock.members.mockResolvedValue([{ id: 1, role: "owner", created_at: "", user }]);
    render(<SettingsPage />, { wrapper: Providers });

    expect(await screen.findByText("you")).toBeInTheDocument();
  });
});

describe("empty state", () => {
  it("draws its illustration for sighted users only", () => {
    const { container } = render(<EmptyState title="Nothing here" />);
    expect(container.querySelector("svg")?.closest("[aria-hidden]")).not.toBeNull();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
