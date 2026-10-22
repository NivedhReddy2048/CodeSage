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

describe("refresh-token blacklisting (#101)", () => {
  it("two different calls with an expired token share one refresh, and both succeed", async () => {
    storeTokens(jwt(-60, "expired"), "refresh-1");
    const calls = stubBackend();
    const original = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>;
    let orgs = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/orgs/")) {
          orgs += 1;
          const auth = ((init?.headers ?? {}) as Record<string, string>).Authorization;
          if (auth !== `Bearer ${FRESH}`) calls.unauthorized += 1;
          return new Response("[]", { status: auth === `Bearer ${FRESH}` ? 200 : 401 });
        }
        return original(url, init);
      }),
    );

    const [me, organizations] = await Promise.all([api.currentUser(), api.organizations()]);

    expect(me).toMatchObject({ github_login: "alice" });
    expect(organizations).toEqual([]);
    expect(calls.refresh).toBe(1);
    expect(calls.unauthorized).toBe(0);
    expect(orgs).toBe(1);
  });

  it("when another tab rotated the shared token first, this tab stays signed in", async () => {
    storeTokens(jwt(-60, "expired"), "refresh-1");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/token/refresh/")) {
          // The other tab won the race: it stored a new pair, and our refresh-1
          // is now blacklisted.
          storeTokens(FRESH, "refresh-from-other-tab");
          return new Response(JSON.stringify({ detail: "Token is blacklisted" }), { status: 401 });
        }
        const auth = ((init?.headers ?? {}) as Record<string, string>).Authorization;
        return auth === `Bearer ${FRESH}`
          ? new Response(JSON.stringify({ id: 1, github_login: "alice" }), { status: 200 })
          : new Response("{}", { status: 401 });
      }),
    );

    await expect(api.currentUser()).resolves.toMatchObject({ github_login: "alice" });
    expect(getRefreshToken()).toBe("refresh-from-other-tab");
  });

  it("a refused refresh with no other tab involved still ends the session", async () => {
    storeTokens(jwt(-60, "expired"), "refresh-1");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Token is blacklisted" }), { status: 401 })),
    );

    await expect(api.currentUser()).rejects.toMatchObject({ status: 401 });
    expect(getRefreshToken()).toBeNull();
  });

  it("signing out revokes the refresh token server-side and clears the session", async () => {
    storeTokens(FRESH, "refresh-to-revoke");
    const calls = stubBackend();
    const posted: unknown[] = [];
    const original = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/logout/")) {
          posted.push(JSON.parse(String(init?.body)));
          return new Response(null, { status: 204 });
        }
        return original(url, init);
      }),
    );

    function SignOut() {
      const { user, signOut } = useAuth();
      return user ? <button onClick={signOut}>Sign out</button> : <p>signed out</p>;
    }
    render(
      <AuthProvider>
        <SignOut />
      </AuthProvider>,
    );
    (await screen.findByRole("button", { name: "Sign out" })).click();

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(posted).toEqual([{ refresh: "refresh-to-revoke" }]);
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(calls.unauthorized).toBe(0);
  });

  it("an unreachable backend never keeps anyone signed in", async () => {
    storeTokens(FRESH, "refresh-x");
    stubBackend();
    const original = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/logout/")) throw new TypeError("Failed to fetch");
        return original(url, init);
      }),
    );
    function SignOut() {
      const { user, signOut } = useAuth();
      return user ? <button onClick={signOut}>Sign out</button> : <p>signed out</p>;
    }
    render(
      <AuthProvider>
        <SignOut />
      </AuthProvider>,
    );
    (await screen.findByRole("button", { name: "Sign out" })).click();

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(getRefreshToken()).toBeNull();
  });
});
