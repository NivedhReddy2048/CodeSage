import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { navigation, nextNavigationMock, resetNavigation } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({ rerunReview: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));

import { AgentProgress } from "@/components/review/agent-progress";
import { AgentsTable } from "@/components/review/agents-table";
import { DiffViewer, unanchoredFindings } from "@/components/review/diff-viewer";
import { FindingsPanel } from "@/components/review/findings-panel";
import { RerunButton } from "@/components/review/rerun-button";
import { ReviewStatusPill } from "@/components/review/status-pill";
import { ApiError } from "@/lib/api";
import type { AgentRun, ReviewFinding } from "@/lib/types";

const DIFF = `diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -10,4 +10,5 @@ def helper():
 def paginate_users(users, page, per_page=10):
-    end = start + per_page
+    end = page + per_page
+    query = "SELECT * FROM users WHERE name = '%s'" % users
     return users[start:end]
`;

const finding = (overrides: Partial<ReviewFinding>): ReviewFinding => ({
  id: 1,
  agent: "security",
  severity: "blocking",
  category: "security",
  file_path: "app/users.py",
  line: 12,
  message: "SQL built from user input.",
  citation: "",
  dismissed: false,
  ...overrides,
});

beforeEach(() => resetNavigation());

describe("diff viewer", () => {
  it("threads a finding directly under the line it points at", () => {
    render(<DiffViewer diff={DIFF} findings={[finding({})]} />);

    const table = screen.getByRole("table", { name: /Changes to app\/users.py/ });
    const rows = within(table).getAllByRole("row");
    const lineRow = rows.findIndex((row) => row.textContent?.includes("SELECT * FROM users"));
    expect(rows[lineRow + 1]).toHaveTextContent("SQL built from user input.");
  });

  it("labels added and removed lines for screen readers, not only by colour", () => {
    render(<DiffViewer diff={DIFF} findings={[]} />);

    expect(screen.getAllByText("added:", { exact: false }).length).toBe(2);
    expect(screen.getAllByText("removed:", { exact: false }).length).toBe(1);
  });

  it("shows a grounded finding's citation", () => {
    render(<DiffViewer diff={DIFF} findings={[finding({ citation: "app/repo.py:4-9" })]} />);
    expect(screen.getByText("app/repo.py:4-9")).toBeInTheDocument();
  });

  it("knows which findings it cannot place", () => {
    const off = finding({ id: 2, line: 400 });
    expect(unanchoredFindings(DIFF, [finding({}), off])).toEqual([off]);
  });
});

describe("findings panel", () => {
  it("groups by severity and jumps to an anchored finding", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const findings = [finding({}), finding({ id: 2, severity: "nit", line: 400, message: "Old line." })];
    render(
      <>
        <DiffViewer diff={DIFF} findings={findings} />
        <FindingsPanel findings={findings} unanchored={[findings[1]]} status="done" />
      </>,
    );

    expect(screen.getByRole("region", { name: "Blocking findings" })).toBeInTheDocument();
    const nits = screen.getByRole("region", { name: "Nits findings" });
    expect(within(nits).getByText(/not on a line the diff shows/)).toBeInTheDocument();
    // Only the anchored one is a button.
    expect(within(nits).queryByRole("button")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "app/users.py:12" }));
    expect(scroll).toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("finding-1");
  });

  it("says plainly when there is nothing to report", () => {
    render(<FindingsPanel findings={[]} unanchored={[]} status="done" />);
    expect(screen.getByText("No issues found")).toBeInTheDocument();
  });
});

describe("agents table", () => {
  const run = (overrides: Partial<AgentRun>): AgentRun => ({
    id: 1,
    name: "security",
    model: "openai/gpt-oss-120b",
    requested_model: "openai/gpt-oss-120b",
    provider: "groq",
    input_tokens: 600,
    output_tokens: 250,
    latency_ms: 1400,
    succeeded: true,
    used_fallback: false,
    findings_count: 1,
    skipped_reason: "",
    error: "",
    error_summary: "",
    detail: "",
    ...overrides,
  });

  it("names the model that served a fallback, and what was asked for", () => {
    render(
      <AgentsTable
        runs={[
          run({
            model: "gemini-flash-lite-latest",
            provider: "gemini",
            used_fallback: true,
          }),
        ]}
      />,
    );

    expect(screen.getByText("gemini-flash-lite-latest")).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-oss-120b").closest("span")).toHaveTextContent("asked for");
    expect(screen.getByText("Fallback")).toBeInTheDocument();
  });

  it("a failed agent shows the short reason, never raw text it was not given", () => {
    render(<AgentsTable runs={[run({ succeeded: false, model: "", error_summary: "AI providers unavailable" })]} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("AI providers unavailable")).toBeInTheDocument();
  });

  it("scales each latency bar to the slowest agent", () => {
    const { container } = render(
      <AgentsTable runs={[run({ id: 1, latency_ms: 2000 }), run({ id: 2, name: "security", latency_ms: 500 })]} />,
    );
    const bars = [...container.querySelectorAll<HTMLElement>("[style*='width']")].map((bar) => bar.style.width);
    expect(bars).toEqual(["100%", "25%"]);
  });

  it("shows tokens and latency", () => {
    render(<AgentsTable runs={[run({})]} />);
    expect(screen.getByText("600 / 250")).toBeInTheDocument();
    expect(screen.getByText("1.4 s")).toBeInTheDocument();
  });
});

describe("status pill", () => {
  it("counts agents while running, in a live region", () => {
    render(
      <ReviewStatusPill
        status="running"
        degraded={false}
        transport="socket"
        progress={{ type: "review.progress", review_id: 1, status: "running", agents: {}, completed: 3, total: 5 }}
      />,
    );
    const pill = screen.getByRole("status");
    expect(pill).toHaveAttribute("aria-live", "polite");
    expect(pill).toHaveTextContent("Reviewing... 3/5 agents");
  });

  it("says when it has fallen back to polling", () => {
    render(<ReviewStatusPill status="running" degraded={false} transport="polling" progress={null} />);
    expect(screen.getByText(/checking every few seconds/)).toBeInTheDocument();
  });

  it("shows degraded over the raw status once finished", () => {
    render(<ReviewStatusPill status="failed" degraded transport="idle" progress={null} />);
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });
});

describe("re-run button", () => {
  it("asks first, then starts the review and opens it", async () => {
    apiMock.rerunReview.mockResolvedValue({ review_id: 99 });
    render(<RerunButton reviewId={31} pullRequest="alice/app#3" />);

    await userEvent.click(screen.getByRole("button", { name: "Re-run review" }));
    const dialog = await screen.findByRole("dialog", { name: "Re-run this review?" });
    expect(apiMock.rerunReview).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("audit log");

    await userEvent.click(within(dialog).getByRole("button", { name: "Re-run review" }));

    expect(apiMock.rerunReview).toHaveBeenCalledWith(31);
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/reviews/99"));
  });

  it("cancel does nothing", async () => {
    render(<RerunButton reviewId={31} pullRequest="alice/app#3" />);

    await userEvent.click(screen.getByRole("button", { name: "Re-run review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(apiMock.rerunReview).not.toHaveBeenCalled();
  });

  it("shows why the server refused", async () => {
    apiMock.rerunReview.mockRejectedValue(
      new ApiError(409, "A review of this pull request is already in progress."),
    );
    render(<RerunButton reviewId={31} pullRequest="alice/app#3" />);

    await userEvent.click(screen.getByRole("button", { name: "Re-run review" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Re-run review" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already in progress");
    expect(navigation.push).not.toHaveBeenCalled();
  });
});

describe("while a review runs", () => {
  it("the findings panel never claims there are none", () => {
    render(<FindingsPanel findings={[]} unanchored={[]} status="running" />);

    expect(screen.getByText("Review in progress")).toBeInTheDocument();
    expect(screen.queryByText(/No issues found|No findings/)).not.toBeInTheDocument();
  });
});

describe("agent progress", () => {
  it("has one step per agent, in graph order, each state in words", () => {
    render(<AgentProgress agents={{ diff_intent: "ok", security: "running", grounding: "failed" }} />);

    const steps = within(screen.getByRole("list", { name: "Agent progress" })).getAllByRole("listitem");
    expect(steps.map((step) => step.querySelector(".sr-only")?.textContent)).toEqual([
      "Diff/Intent: done",
      "Static analysis: waiting",
      "Security: running",
      "Codebase grounding: failed",
      "Test coverage: waiting",
    ]);
  });
});
