import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ currentUser: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
}));

import { AuthProvider, useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";
import { getAccessToken, setSelectedOrganizationId, storeTokens } from "@/lib/tokens";

function Probe() {
  const { user, loading, error } = useAuth();
  if (loading) return <p>loading</p>;
  return <p>{user ? `user:${user.github_login}` : `signed-out error:${error ?? "none"}`}</p>;
}

describe("AuthProvider", () => {
  it("a rejected token (401) ends the session", async () => {
    storeTokens("expired", "expired");
    apiMock.currentUser.mockRejectedValue(new ApiError(401, "Token is invalid"));

    render(<AuthProvider><Probe /></AuthProvider>);

    await waitFor(() => expect(screen.getByText("signed-out error:none")).toBeInTheDocument());
    expect(getAccessToken()).toBeNull();
  });

  it("an unreachable API keeps the session and reports why", async () => {
    // The CORS-preflight failure that signed people out on every other page load.
    storeTokens("valid", "valid");
    setSelectedOrganizationId(20);
    apiMock.currentUser.mockRejectedValue(
      new ApiError(0, "Could not reach the API. Is the backend running?"),
    );

    render(<AuthProvider><Probe /></AuthProvider>);

    await waitFor(() =>
      expect(screen.getByText(/signed-out error:Could not reach the API/)).toBeInTheDocument(),
    );
    expect(getAccessToken()).toBe("valid");
    expect(window.localStorage.getItem("codesage.organization")).toBe("20");
  });

  it("a server error keeps the session too", async () => {
    storeTokens("valid", "valid");
    apiMock.currentUser.mockRejectedValue(new ApiError(502, "Bad gateway"));

    render(<AuthProvider><Probe /></AuthProvider>);

    await waitFor(() => expect(screen.getByText(/Bad gateway/)).toBeInTheDocument());
    expect(getAccessToken()).toBe("valid");
  });
});
