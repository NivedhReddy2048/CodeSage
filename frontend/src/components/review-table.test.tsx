import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewTable } from "@/components/review-table";
import type { ReviewListItem } from "@/lib/types";

const row = (overrides: Partial<ReviewListItem>): ReviewListItem => ({
  id: 1,
  repository: "NivedhReddy2048/codesage-testbed",
  repository_id: 1,
  pr_number: 7,
  pr_title: "Read the key from the environment",
  status: "done",
  stalled: false,
  trigger: "webhook",
  degraded: false,
  used_fallback: false,
  head_sha: "7693464abcdef",
  model_used: "m",
  duration_ms: 3800,
  estimated_cost_inr: "0.141600",
  finding_count: 3,
  blocking_count: 2,
  nit_count: 1,
  created_at: new Date().toISOString(),
  ...overrides,
});

describe("review table", () => {
  it("says what the findings are, in words", () => {
    render(<ReviewTable reviews={[row({}), row({ id: 2, finding_count: 0, blocking_count: 0, nit_count: 0 })]} />);

    const [, first, second] = screen.getAllByRole("row");
    expect(first).toHaveTextContent("2 blocking · 1 nit");
    expect(second).toHaveTextContent("None");
  });

  it("shows which commit was reviewed, and tags a re-run", () => {
    render(<ReviewTable reviews={[row({}), row({ id: 2, trigger: "rerun" })]} />);

    const [, webhook, rerun] = screen.getAllByRole("row");
    expect(within(webhook).getByText("7693464")).toHaveAttribute("title", "Head commit 7693464abcdef");
    expect(within(webhook).queryByText("Re-run")).not.toBeInTheDocument();
    expect(within(rerun).getByText("Re-run")).toBeInTheDocument();
  });

  it("shows cost at two decimals with the exact estimate on hover", () => {
    render(<ReviewTable reviews={[row({})]} />);

    expect(screen.getByText("₹0.14")).toHaveAttribute("title", "Exact estimate: ₹0.1416");
  });
});
