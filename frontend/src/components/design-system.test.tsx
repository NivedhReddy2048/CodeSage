import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatusBadge, reviewStatusKind, type StatusKind } from "@/components/status-badge";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";
import { NativeSelect } from "@/components/ui/native-select";
import { SegmentedControl } from "@/components/ui/segmented-control";

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

describe("NativeSelect", () => {
  it("stays a labelled native select, with a decorative chevron", async () => {
    const onChange = vi.fn();
    const { container } = render(
      <>
        <label htmlFor="repo">Repository</label>
        <NativeSelect id="repo" value="" onChange={(event) => onChange(event.target.value)}>
          <option value="">All repositories</option>
          <option value="7">acme/api</option>
        </NativeSelect>
      </>,
    );

    const select = screen.getByRole("combobox", { name: "Repository" });
    await userEvent.selectOptions(select, "7");
    expect(onChange).toHaveBeenCalledWith("7");
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("SegmentedControl", () => {
  const options = [
    { value: "7", label: "Last 7 days" },
    { value: "30", label: "Last 30 days" },
  ] as const;

  it("is a named radio group whose choice is checked", () => {
    render(
      <SegmentedControl legend="Period" name="period" value="30" options={options} onValueChange={vi.fn()} />,
    );

    expect(screen.getByRole("group", { name: "Period" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Last 30 days" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Last 7 days" })).not.toBeChecked();
  });

  it("reports a new choice by click and by arrow key", async () => {
    const onValueChange = vi.fn();
    render(
      <SegmentedControl legend="Period" name="period" value="7" options={options} onValueChange={onValueChange} />,
    );

    await userEvent.click(screen.getByText("Last 30 days"));
    expect(onValueChange).toHaveBeenLastCalledWith("30");

    onValueChange.mockClear();
    screen.getByRole("radio", { name: "Last 7 days" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onValueChange).toHaveBeenLastCalledWith("30");
  });

  it("can keep its legend for screen readers only", () => {
    render(
      <SegmentedControl legend="Period" name="period" value="7" options={options} onValueChange={vi.fn()} hideLegend />,
    );
    expect(screen.getByText("Period")).toHaveClass("sr-only");
  });
});
