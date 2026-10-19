import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { navigation, nextNavigationMock, resetNavigation } from "@/test/mocks";

vi.mock("next/navigation", () => nextNavigationMock());

const apiMock = vi.hoisted(() => ({ completeGitHubLogin: vi.fn(), currentUser: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));

const auth = vi.hoisted(() => ({ reload: vi.fn() }));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: null, loading: false, error: null, signOut: vi.fn(), reload: auth.reload }),
}));

import AuthCallbackPage from "@/app/auth/callback/page";
import { ApiError } from "@/lib/api";
import { SignInError, completeSignIn, resetExchangesForTests } from "@/lib/oauth";
import {
  clearSession,
  getAccessToken,
  getSelectedOrganizationId,
  setSelectedOrganizationId,
  storeOAuthState,
  storeTokens,
} from "@/lib/tokens";

function arriveAt(code: string, state = "signed-state") {
  storeOAuthState(state);
  navigation.search = new URLSearchParams({ code, state });
}

function renderStrict() {
  // Strict Mode is the point: it runs the effect, cleans it up, and runs it again.
  return render(
    <StrictMode>
      <AuthCallbackPage />
    </StrictMode>,
  );
}

beforeEach(() => {
  resetNavigation();
  resetExchangesForTests();
  window.sessionStorage.clear();
  auth.reload.mockReset().mockResolvedValue(undefined);
  apiMock.completeGitHubLogin.mockReset().mockResolvedValue({
    access: "new-access",
    refresh: "new-refresh",
    user: {},
    created: false,
  });
});

describe("the OAuth callback", () => {
  it("exchanges the code exactly once under Strict Mode's double effect, and still finishes", async () => {
    arriveAt("code-1");
    renderStrict();

    // The regression: the single exchange used to succeed with nobody listening,
    // leaving "Completing sign-in..." on screen forever.
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(apiMock.completeGitHubLogin).toHaveBeenCalledOnce();
    expect(apiMock.completeGitHubLogin).toHaveBeenCalledWith("code-1", "signed-state");
    expect(getAccessToken()).toBe("new-access");
    expect(auth.reload).toHaveBeenCalledOnce();
  });

  it("a remount mid-exchange joins the same exchange instead of starting another", async () => {
    let finish: () => void = () => undefined;
    apiMock.completeGitHubLogin.mockReturnValue(
      new Promise((resolve) => {
        finish = () => resolve({ access: "a", refresh: "r", user: {}, created: false });
      }),
    );
    arriveAt("code-2");
    const first = renderStrict();
    first.unmount();
    renderStrict();

    finish();

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(apiMock.completeGitHubLogin).toHaveBeenCalledOnce();
  });

  it("signs in a second time after signing out", async () => {
    arriveAt("first-code", "state-1");
    const first = renderStrict();
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    first.unmount();
    setSelectedOrganizationId(42); // chosen during the first session

    clearSession(); // what Sign out does
    expect(getAccessToken()).toBeNull();
    expect(getSelectedOrganizationId()).toBeNull();
    expect(window.sessionStorage.getItem("codesage.oauth_state")).toBeNull();

    // GitHub skips consent the second time and redirects straight back.
    navigation.replace.mockReset();
    apiMock.completeGitHubLogin.mockResolvedValue({ access: "second", refresh: "r2", user: {}, created: false });
    arriveAt("second-code", "state-2");
    renderStrict();

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(apiMock.completeGitHubLogin).toHaveBeenLastCalledWith("second-code", "state-2");
    expect(apiMock.completeGitHubLogin).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBe("second");
  });

  it("a stale workspace from a previous session never survives a new sign-in", async () => {
    storeTokens("old", "old");
    setSelectedOrganizationId(42);
    arriveAt("code-3");
    renderStrict();

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(getSelectedOrganizationId()).toBeNull();
    expect(getAccessToken()).toBe("new-access");
  });

  it("a failed exchange shows a short error and a way back, never the raw detail", async () => {
    apiMock.completeGitHubLogin.mockRejectedValue(
      new ApiError(400, "GitHub rejected the code: bad_verification_code (The code passed is incorrect or expired.)"),
    );
    arriveAt("used-code");
    renderStrict();

    expect(await screen.findByRole("heading", { name: "Sign-in failed" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("GitHub did not accept this sign-in. It may have expired.");
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/login");
    expect(document.body.textContent).not.toContain("bad_verification_code");
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(apiMock.completeGitHubLogin).toHaveBeenCalledOnce();
  });

  it("an unreachable backend says so", async () => {
    apiMock.completeGitHubLogin.mockRejectedValue(new ApiError(0, "Could not reach the API."));
    arriveAt("code-4");
    renderStrict();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach CodeSage");
  });

  it("a cancelled sign-in on GitHub is explained", async () => {
    navigation.search = new URLSearchParams({ error: "access_denied", state: "s" });
    renderStrict();

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in was cancelled on GitHub.");
    expect(apiMock.completeGitHubLogin).not.toHaveBeenCalled();
  });

  it("a state from another tab is refused before the code is spent", async () => {
    storeOAuthState("this-tab");
    navigation.search = new URLSearchParams({ code: "c", state: "other-tab" });
    renderStrict();

    expect(await screen.findByRole("alert")).toHaveTextContent("started in another tab");
    expect(apiMock.completeGitHubLogin).not.toHaveBeenCalled();
  });
});

describe("completeSignIn", () => {
  it("gives up after the timeout instead of waiting forever", async () => {
    apiMock.completeGitHubLogin.mockReturnValue(new Promise(() => undefined));

    const result = completeSignIn(new URLSearchParams({ code: "slow", state: "s" }), auth.reload, 20);

    await expect(result).rejects.toBeInstanceOf(SignInError);
    await expect(result).rejects.toThrow("taking too long");
  });
});

describe("sign out", () => {
  it("clears everything session-related", () => {
    storeTokens("a", "r");
    setSelectedOrganizationId(7);
    storeOAuthState("pending");

    clearSession();

    expect(window.localStorage.getItem("codesage.access")).toBeNull();
    expect(window.localStorage.getItem("codesage.refresh")).toBeNull();
    expect(window.localStorage.getItem("codesage.organization")).toBeNull();
    expect(window.sessionStorage.getItem("codesage.oauth_state")).toBeNull();
  });
});
