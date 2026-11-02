import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { demoLimits } from "@/test/mocks";

const apiMock = vi.hoisted(() => ({ demoLimits: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));

import { DemoLimitBanner, DemoUsage } from "@/components/demo-limits";

function limited(scope: "workspace" | "global") {
  return {
    ...demoLimits,
    reviews: {
      ...demoLimits.reviews,
      workspace: { used: scope === "workspace" ? 5 : 2, limit: 5 },
      global: { used: scope === "global" ? 35 : 20, limit: 35 },
      limited: true,
      scope,
    },
  };
}

beforeEach(() => apiMock.demoLimits.mockResolvedValue(demoLimits));

describe("free-demo limits", () => {
  it("shows no banner while the workspace is under its caps", async () => {
    render(<DemoLimitBanner />);

    await vi.waitFor(() => expect(apiMock.demoLimits).toHaveBeenCalled());
    expect(screen.queryByText("Daily free-demo limit reached")).not.toBeInTheDocument();
  });

  it("says when the workspace's own cap is reached, and when PRs will be reviewed", async () => {
    apiMock.demoLimits.mockResolvedValue(limited("workspace"));
    render(<DemoLimitBanner />);

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("Daily free-demo limit reached");
    expect(banner).toHaveTextContent("This workspace has used its 5 free reviews for today.");
    expect(banner).toHaveTextContent("reviewed automatically after the limit resets at 05:30 IST");
  });

  it("names the shared cap when the whole demo is out for the day", async () => {
    apiMock.demoLimits.mockResolvedValue(limited("global"));
    render(<DemoLimitBanner />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The demo's shared limit of 35 reviews for today is used up.",
    );
  });

  it("puts the cap and today's usage on the dashboard", async () => {
    render(<DemoUsage />);

    expect(screen.getByText("Free demo, 5 reviews/day per workspace")).toBeInTheDocument();
    expect(await screen.findByText(/1 used today/)).toHaveTextContent(
      "1 used today · public repositories only, up to 3 per workspace",
    );
  });
});
