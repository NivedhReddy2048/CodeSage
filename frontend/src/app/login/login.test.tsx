import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { ExampleReview } from "@/components/landing/example-review";
import { ApiError } from "@/lib/api";

function renderLogin() {
  return render(
    <ThemeProvider attribute="class">
      <LoginPage />
    </ThemeProvider>,
  );
}

/**
 * The site header. Testing Library also counts the diff viewer's per-file <header>
 * as a banner, though it sits inside <main>; the page header comes first.
 */
function siteHeader() {
  return within(screen.getAllByRole("banner")[0]);
}

/** The hero's sign-in card, where the main "Continue with GitHub" lives. */
function signInCard() {
  return within(screen.getByRole("region", { name: "Sign in" }));
}

beforeEach(() => resetNavigation());
afterEach(() => vi.unstubAllGlobals());

describe("login page", () => {
  it("introduces the product: name, one-line pitch, three features", () => {
    renderLogin();

    expect(siteHeader().getByText("CodeSage")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Every pull request/);
    expect(
      screen.getByText("AI code review for GitHub pull requests that knows your codebase, not just the diff."),
    ).toBeInTheDocument();
    for (const feature of ["Multi-agent review", "Grounded in your codebase", "Inline PR comments"]) {
      expect(screen.getByText(feature)).toBeInTheDocument();
    }
  });

  it("links to the repository in a new tab", () => {
    renderLogin();

    const link = siteHeader().getByRole("link", { name: "View on GitHub" });
    expect(link).toHaveAttribute("href", REPOSITORY_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("jumps to each section from the header", () => {
    renderLogin();

    const nav = screen.getByRole("navigation", { name: "Page sections" });
    for (const [name, id] of [
      ["How it works", "how-it-works"],
      ["Architecture", "architecture"],
      ["Example review", "example"],
    ]) {
      expect(within(nav).getByRole("link", { name })).toHaveAttribute("href", `#${id}`);
      expect(document.getElementById(id)).not.toBeNull();
    }
  });

  it("stores the state before leaving for GitHub", async () => {
    apiMock.startGitHubLogin.mockResolvedValue({ authorize_url: "about:blank", state: "signed" });
    renderLogin();

    await userEvent.click(signInCard().getByRole("button", { name: "Continue with GitHub" }));

    expect(window.sessionStorage.getItem("codesage.oauth_state")).toBe("signed");
  });

  it("a failure to start is a short message, not the API's text", async () => {
    apiMock.startGitHubLogin.mockRejectedValue(new ApiError(500, "Traceback: KeyError GITHUB_CLIENT_ID"));
    renderLogin();

    await userEvent.click(signInCard().getByRole("button", { name: "Continue with GitHub" }));

    expect(await signInCard().findByRole("alert")).toHaveTextContent(
      "Could not start sign-in. Please try again.",
    );
    expect(document.body.textContent).not.toContain("Traceback");
  });

  it("reports a failure next to the button that was pressed, once", async () => {
    apiMock.startGitHubLogin.mockRejectedValue(new ApiError(0, "offline"));
    renderLogin();

    const cta = within(screen.getByRole("region", { name: "Try it on your next pull request" }));
    await userEvent.click(cta.getByRole("button", { name: "Continue with GitHub" }));

    expect(await cta.findByRole("alert")).toHaveTextContent("Could not reach CodeSage");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("describes the pipeline as the code runs it", () => {
    renderLogin();

    const pipeline = screen.getByRole("list", { name: "Review pipeline, in order" });
    expect(pipeline).toHaveTextContent(/Diff\/Intent.*Then four agents in parallel.*Synthesis.*GitHub/);
    expect(pipeline).toHaveTextContent("ruff + bandit on Python a pattern scan on JS/TS");
    expect(document.body.textContent).not.toMatch(/tree-sitter|eslint/i);
    expect(screen.getByText("Groq → Gemini fallback → labelled degraded mode")).toBeInTheDocument();
    expect(screen.getByText("Live progress over WebSockets")).toBeInTheDocument();
  });

  it("claims no social proof", () => {
    renderLogin();

    expect(document.body.textContent).not.toMatch(
      /testimonial|trusted by|customers|users love|\d+\s*(teams|developers|companies)/i,
    );
  });

  it("labels the example's cost as an estimate, with actual spend zero", () => {
    renderLogin();

    const costLine = screen.getByText(
      (_, element) =>
        element?.tagName === "P" &&
        /est\. ₹0\.07 at paid-tier rates · actual spend ₹0/.test(element.textContent ?? ""),
    );
    expect(costLine).toBeInTheDocument();
  });
});

describe("example review", () => {
  it("is badged as an example and renders a blocking finding with its citation", () => {
    render(<ExampleReview />);

    expect(screen.getByText("Example")).toBeInTheDocument();
    expect(screen.getByText(/range\(len\(users\) \+ 1\) runs one index past the end/)).toBeInTheDocument();
    expect(screen.getByText("app/exports.py:22-31", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Per-agent telemetry" }).children).toHaveLength(5);
  });

  it("makes no network requests at all", () => {
    const fetchSpy = vi.fn();
    const socketSpy = vi.fn();
    const xhrSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", socketSpy);
    vi.stubGlobal("XMLHttpRequest", xhrSpy);

    const { container } = render(<ExampleReview />);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(socketSpy).not.toHaveBeenCalled();
    expect(xhrSpy).not.toHaveBeenCalled();
    // Nothing that would load a resource either.
    expect(container.querySelectorAll("img, iframe, video, audio, source, link, script")).toHaveLength(0);
  });
});
