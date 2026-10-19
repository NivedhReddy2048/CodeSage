import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatusBadge, reviewStatusKind, type StatusKind } from "@/components/status-badge";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";

describe("StatusBadge", () => {
  const kinds: StatusKind[] = [
    "blocking",
    "nit",
    "degraded",
    "fallback",
    "ok",
    "done",
    "running",
    "pending",
    "failed",
    "skipped",
  ];

  it.each(kinds)("%s carries a word, not just a colour", (kind) => {
    const { container } = render(<StatusBadge kind={kind} />);
    const badge = container.querySelector(`[data-status="${kind}"]`);

    expect(badge).not.toBeNull();
    expect(badge?.textContent?.trim().length).toBeGreaterThan(1);
    // The icon is decorative; the word is what assistive tech reads.
    expect(badge?.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("accepts a custom label", () => {
    render(<StatusBadge kind="running" label="3/5 agents" />);
    expect(screen.getByText("3/5 agents")).toBeInTheDocument();
  });

  it("does not spin for people who asked for reduced motion", () => {
    const { container } = render(<StatusBadge kind="running" />);
    expect(container.querySelector("svg")?.getAttribute("class")).toContain(
      "motion-reduce:animate-none",
    );
  });

  it("ranks degraded above the status it sits on", () => {
    expect(reviewStatusKind({ status: "failed", degraded: true })).toBe("degraded");
    expect(reviewStatusKind({ status: "failed", degraded: false })).toBe("failed");
    expect(reviewStatusKind({ status: "done", degraded: false })).toBe("done");
    expect(reviewStatusKind({ status: "running", degraded: false })).toBe("running");
    expect(reviewStatusKind({ status: "pending", degraded: false })).toBe("pending");
  });
});

describe("states", () => {
  it("an error is announced and offers a retry", async () => {
    const retry = vi.fn();
    render(<ErrorState message="The API is down." onRetry={retry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("The API is down.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("an empty state explains and can carry an action", () => {
    render(<EmptyState title="No reviews yet" description="Open a PR." action={<button>Go</button>} />);

    expect(screen.getByText("No reviews yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
  });

  it("a skeleton is a labelled status, so screen readers hear 'loading'", () => {
    render(<ListSkeleton label="Loading reviews" />);
    expect(screen.getByRole("status", { name: "Loading reviews" })).toBeInTheDocument();
  });
});
