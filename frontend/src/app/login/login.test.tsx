import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { nextNavigationMock, resetNavigation } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({ startGitHubLogin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: null, loading: false, error: null, signOut: vi.fn(), reload: vi.fn() }),
}));

import LoginPage, { REPOSITORY_URL } from "@/app/login/page";
import { ApiError } from "@/lib/api";

function renderLogin() {
  return render(
    <ThemeProvider attribute="class">
      <LoginPage />
    </ThemeProvider>,
  );
}

beforeEach(() => resetNavigation());

describe("login page", () => {
  it("introduces the product: logo, one-line pitch, three features", () => {
    renderLogin();

    expect(screen.getByRole("img", { name: "CodeSage logo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "CodeSage" })).toBeInTheDocument();
    expect(screen.getByText(/knows your codebase/)).toBeInTheDocument();
    for (const feature of ["Multi-agent review", "Grounded in your codebase", "Inline PR comments"]) {
      expect(screen.getByText(feature)).toBeInTheDocument();
    }
  });

  it("links to the repository in a new tab", () => {
    renderLogin();

    const link = screen.getByRole("link", { name: "View on GitHub" });
    expect(link).toHaveAttribute("href", REPOSITORY_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("stores the state before leaving for GitHub", async () => {
    apiMock.startGitHubLogin.mockResolvedValue({ authorize_url: "about:blank", state: "signed" });
    renderLogin();

    await userEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));

    expect(window.sessionStorage.getItem("codesage.oauth_state")).toBe("signed");
  });

  it("a failure to start is a short message, not the API's text", async () => {
    apiMock.startGitHubLogin.mockRejectedValue(new ApiError(500, "Traceback: KeyError GITHUB_CLIENT_ID"));
    renderLogin();

    await userEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not start sign-in. Please try again.");
    expect(document.body.textContent).not.toContain("Traceback");
  });
});
