import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { BarChart } from "@/components/charts/bar-chart";
import { ChartCard, DataTable } from "@/components/charts/chart-card";
import { ColumnChart } from "@/components/charts/column-chart";
import { barPath, columnPath, compact, niceScale } from "@/components/charts/scale";

describe("scale", () => {
  it("rounds the axis to clean ticks", () => {
    expect(niceScale(9)).toEqual({ max: 10, ticks: [0, 2.5, 5, 7.5, 10] });
    expect(niceScale(27)).toEqual({ max: 30, ticks: [0, 10, 20, 30] });
    expect(niceScale(0)).toEqual({ max: 1, ticks: [0, 1] });
  });

  it("compacts from 1,000 up", () => {
    expect(compact(950)).toBe("950");
    expect(compact(1284)).toBe("1.3K");
  });

  it("rounds only the data end of a mark", () => {
    // Column: starts at the baseline corner, curves only at the top.
    expect(columnPath(0, 10, 20, 50)).toMatch(/^M0,60 V14 Q0,10 4,10/);
    // Bar: square at the left baseline, curves only on the right.
    expect(barPath(0, 0, 100, 16)).toMatch(/^M0,0 H96 Q100,0 100,4/);
    // Nothing to draw for zero.
    expect(columnPath(0, 10, 20, 0)).toBe("");
  });
});

const days = [
  { key: "2026-10-17", label: "Oct 17", value: 2 },
  { key: "2026-10-18", label: "Oct 18", value: 7 },
  { key: "2026-10-19", label: "Oct 19", value: 0 },
];

describe("ColumnChart", () => {
  it("labels only the peak, not every column", () => {
    const { container } = render(<ColumnChart points={days} unit="reviews" />);

    // Value labels wear the primary text token; axis ticks are muted.
    const valueLabels = [...container.querySelectorAll("text.fill-foreground")].map((node) => node.textContent);
    expect(valueLabels).toEqual(["7"]);
    // Zero draws nothing rather than a sliver.
    expect([...container.querySelectorAll("path")].filter((p) => p.getAttribute("d"))).toHaveLength(2);
  });

  it("reads each day with the arrow keys, the same readout as hover", () => {
    render(<ColumnChart points={days} unit="reviews" />);
    const chart = screen.getByRole("group", { name: /reviews per day/ });

    fireEvent.focus(chart);
    expect(screen.getByRole("status")).toHaveTextContent("0 reviews");
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(screen.getByRole("status")).toHaveTextContent("7 reviews");
    expect(screen.getByRole("status")).toHaveTextContent("Oct 18");
    fireEvent.keyDown(chart, { key: "Escape" });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("BarChart", () => {
  const series = [
    { label: "Blocking", color: "var(--series-1)" },
    { label: "Nits", color: "var(--series-2)" },
  ];

  it("gives each row an accessible readout of every series", () => {
    render(
      <BarChart
        rows={[{ key: "security", label: "Security", values: [4, 1] }]}
        series={series}
        unit="findings"
      />,
    );

    expect(screen.getByRole("listitem", { name: "Security: 5 findings (4 blocking, 1 nits)" })).toBeInTheDocument();
  });

  it("shows the per-series tooltip on keyboard focus", () => {
    render(<BarChart rows={[{ key: "s", label: "Security", values: [4, 1] }]} series={series} unit="findings" />);

    fireEvent.focus(screen.getByRole("listitem"));

    const tip = screen.getByRole("status");
    expect(within(tip).getByText("4")).toBeInTheDocument();
    expect(within(tip).getByText("Nits")).toBeInTheDocument();
  });

  it("never colours text with the series colour", () => {
    const { container } = render(
      <BarChart rows={[{ key: "s", label: "Security", values: [3] }]} series={[series[0]]} unit="findings" />,
    );
    for (const node of container.querySelectorAll("[style]")) {
      expect((node as HTMLElement).style.color).toBe("");
    }
  });
});

describe("ChartCard", () => {
  const table = <DataTable columns={[{ label: "Day" }, { label: "Reviews", numeric: true }]} rows={[["Oct 18", 7]]} />;

  it("has a table view for every chart", async () => {
    render(
      <ChartCard title="Reviews per day" table={table}>
        <p>the chart</p>
      </ChartCard>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Show table" }));

    expect(screen.getByRole("table")).toHaveTextContent("Oct 18");
    expect(screen.queryByText("the chart")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show chart" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a legend for two series and none for one", () => {
    const two = [
      { label: "Blocking", color: "red" },
      { label: "Nits", color: "blue" },
    ];
    const { rerender } = render(
      <ChartCard title="t" table={table} legend={two}>
        x
      </ChartCard>,
    );
    expect(screen.getByRole("list", { name: "Legend" })).toBeInTheDocument();

    rerender(
      <ChartCard title="t" table={table} legend={[two[0]]}>
        x
      </ChartCard>,
    );
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
  });

  it("dims, rather than blanks, while a new slice loads", () => {
    render(
      <ChartCard title="Reviews per day" table={table} stale>
        x
      </ChartCard>,
    );
    expect(screen.getByRole("figure")).toHaveAttribute("aria-busy", "true");
  });
});
