/**
 * Page load with an expired access token must not produce a 401.
 *
 * The access token lives 30 minutes and was only refreshed after a 401. Under Strict
 * Mode the auth provider's mount effect runs twice, so opening the app after a break
 * sent `/api/auth/me/` twice with the expired token: two 401s in the console, then one
 * shared refresh replayed both. These run the real API client and the real provider.
 */
import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/components/auth-provider";
import { api, ensureFreshToken, tokenExpiresSoon } from "@/lib/api";
import { clearSession, getAccessToken, getRefreshToken, storeTokens } from "@/lib/tokens";

function jwt(expiresInSeconds: number, label: string) {
  const payload = { exp: Math.floor(Date.now() / 1000) + expiresInSeconds, jti: label };
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${encode({ alg: "HS256" })}.${encode(payload)}.signature`;
}

const FRESH = jwt(1800, "fresh");

/** A backend that accepts only FRESH, rotates the refresh token, and counts 401s. */
function stubBackend() {
  const calls = { me: 0, refresh: 0, unauthorized: 0 };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      if (url.endsWith("/api/auth/token/refresh/")) {
        calls.refresh += 1;
        return new Response(JSON.stringify({ access: FRESH, refresh: "refresh-2" }), { status: 200 });
      }
      if (url.endsWith("/api/auth/me/")) {
        calls.me += 1;
        if (headers.Authorization !== `Bearer ${FRESH}`) {
          calls.unauthorized += 1;
          return new Response(JSON.stringify({ detail: "Token is invalid" }), { status: 401 });
        }
        return new Response(JSON.stringify({ id: 1, github_login: "alice" }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function Who() {
  const { user, loading } = useAuth();
  return <p>{loading ? "loading" : (user?.github_login ?? "signed out")}</p>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  clearSession();
});

describe("token refresh", () => {
  it("a page load after the access token expired logs no 401", async () => {
    storeTokens(jwt(-60, "expired"), "refresh-1");
    const calls = stubBackend();

    render(
      <StrictMode>
        <AuthProvider>
          <Who />
        </AuthProvider>
      </StrictMode>,
    );

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(calls.unauthorized).toBe(0);
    // Both Strict Mode effect runs shared one refresh.
    expect(calls.refresh).toBe(1);
    expect(getAccessToken()).toBe(FRESH);
    expect(getRefreshToken()).toBe("refresh-2");
  });

  it("a token that is still valid is sent as it is", async () => {
    storeTokens(FRESH, "refresh-1");
    const calls = stubBackend();

    await api.currentUser();

    expect(calls).toEqual({ me: 1, refresh: 0, unauthorized: 0 });
  });

  it("a revoked token still gets one refresh and a replay", async () => {
    // Unexpired by its own claim, but the server no longer accepts it.
    storeTokens(jwt(1800, "revoked"), "refresh-1");
    const calls = stubBackend();

    await expect(api.currentUser()).resolves.toMatchObject({ github_login: "alice" });
    expect(calls).toEqual({ me: 2, refresh: 1, unauthorized: 1 });
  });

  it("the progress socket's 4401 renews the token without a /me round trip", async () => {
    storeTokens(jwt(1800, "rejected-by-socket"), "refresh-1");
    const calls = stubBackend();

    await ensureFreshToken();

    expect(calls).toEqual({ me: 0, refresh: 1, unauthorized: 0 });
    expect(getAccessToken()).toBe(FRESH);
  });

  it("reads expiry from the claim, and leaves unreadable tokens to the server", () => {
    expect(tokenExpiresSoon(jwt(-1, "x"))).toBe(true);
    expect(tokenExpiresSoon(jwt(10, "x"))).toBe(true); // inside the 30 s margin
    expect(tokenExpiresSoon(jwt(600, "x"))).toBe(false);
    expect(tokenExpiresSoon("a-token")).toBe(false);
    expect(tokenExpiresSoon("a.not-base64!.c")).toBe(false);
  });
});
