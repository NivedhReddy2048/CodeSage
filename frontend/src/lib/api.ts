/**
 * Typed client for the CodeSage API.
 *
 * On a 401 the client tries the refresh endpoint exactly once and replays the
 * original request. Concurrent 401s share a single in-flight refresh, so a page that
 * fires several requests at once does not spend several refresh tokens — with
 * ROTATE_REFRESH_TOKENS on the backend, racing refreshes would invalidate each other.
 */

import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  storeTokens,
} from "@/lib/tokens";
import type {
  GitHubStartResponse,
  LoginResponse,
  Organization,
  User,
} from "@/lib/types";

const BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Pull a human-readable message out of DRF's several error shapes. */
async function readErrorMessage(response: Response): Promise<string> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return response.statusText || `Request failed (${response.status})`;
  }

  if (typeof payload === "string") return payload;

  if (payload && typeof payload === "object") {
    const body = payload as Record<string, unknown>;
    if (typeof body.detail === "string") return body.detail;

    // Field errors arrive as { field: ["message", ...] }.
    const first = Object.values(body)[0];
    if (Array.isArray(first) && typeof first[0] === "string") return first[0];
  }

  return `Request failed (${response.status})`;
}

let refreshInFlight: Promise<boolean> | null = null;

/** Exchange the refresh token for a new access token. Returns whether it worked. */
function refreshAccessToken(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    const refresh = getRefreshToken();
    if (!refresh) return false;

    try {
      const response = await fetch(`${BASE_URL}/api/auth/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });

      if (!response.ok) {
        clearTokens();
        return false;
      }

      const data = (await response.json()) as {
        access: string;
        refresh?: string;
      };
      // ROTATE_REFRESH_TOKENS is on, so keep the new refresh token when one comes back.
      storeTokens(data.access, data.refresh ?? refresh);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
};

async function request<T>(
  path: string,
  { method = "GET", body, auth = true }: RequestOptions = {},
): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";

    if (auth) {
      const token = getAccessToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    }

    return fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let response: Response;
  try {
    response = await send();
  } catch {
    throw new ApiError(0, "Could not reach the API. Is the backend running?");
  }

  if (response.status === 401 && auth && getRefreshToken()) {
    if (await refreshAccessToken()) {
      response = await send();
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  startGitHubLogin: () =>
    request<GitHubStartResponse>("/api/auth/github/start/", { auth: false }),

  completeGitHubLogin: (code: string, state: string) =>
    request<LoginResponse>("/api/auth/github/callback/", {
      method: "POST",
      body: { code, state },
      auth: false,
    }),

  currentUser: () => request<User>("/api/auth/me/"),

  organizations: () => request<Organization[]>("/api/orgs/"),
};
