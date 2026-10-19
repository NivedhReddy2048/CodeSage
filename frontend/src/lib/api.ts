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
  getSelectedOrganizationId,
  storeTokens,
} from "@/lib/tokens";
import type {
  AuditEntry,
  ConnectedRepository,
  IngestionJob,
  IngestionState,
  GitHubStartResponse,
  InstallableResponse,
  LoginResponse,
  Member,
  Organization,
  OrganizationRole,
  Paginated,
  Review,
  ReviewDiff,
  ReviewListItem,
  ReviewProgress,
  ReviewSummary,
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
      const organization = getSelectedOrganizationId();
      if (organization) headers["X-Organization-Id"] = String(organization);
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

  repositories: () => request<ConnectedRepository[]>("/api/repos/"),

  installableRepositories: () =>
    request<InstallableResponse>("/api/repos/installable/"),

  connectRepository: (githubId: number) =>
    request<ConnectedRepository>("/api/repos/connect/", {
      method: "POST",
      body: { github_id: githubId },
    }),

  disconnectRepository: (id: number) =>
    request<void>(`/api/repos/${id}/`, { method: "DELETE" }),

  ingestionStatus: (id: number) =>
    request<IngestionState>(`/api/repos/${id}/ingestion/`),

  reindexRepository: (id: number) =>
    request<IngestionJob>(`/api/repos/${id}/reindex/`, { method: "POST" }),

  review: (id: number) => request<Review>(`/api/reviews/${id}/`),

  reviewStatus: (id: number) => request<ReviewProgress>(`/api/reviews/${id}/status/`),

  reviewDiff: (id: number) => request<ReviewDiff>(`/api/reviews/${id}/diff/`),

  rerunReview: (id: number) =>
    request<{ review_id: number }>(`/api/reviews/${id}/rerun/`, { method: "POST" }),

  repositoryReviews: (id: number) =>
    request<ReviewSummary[]>(`/api/repos/${id}/reviews/`),

  reviews: (params: Record<string, string | number | undefined> = {}) =>
    request<Paginated<ReviewListItem>>(`/api/reviews/${query(params)}`),

  members: () => request<Member[]>("/api/orgs/members/"),

  auditLog: (params: Record<string, string | number | undefined> = {}) =>
    request<Paginated<AuditEntry>>(`/api/audit-log/${query(params)}`),

  updateMemberRole: (membershipId: number, role: OrganizationRole) =>
    request<Member>(`/api/orgs/members/${membershipId}/`, {
      method: "PATCH",
      body: { role },
    }),
};

/** The WebSocket URL for a path on the API host (http -> ws, https -> wss). */
export function wsUrl(path: string) {
  return `${BASE_URL.replace(/^http/, "ws")}${path}`;
}

/** Make sure the stored access token is fresh, refreshing it if needed. */
export async function ensureFreshToken() {
  await api.currentUser();
}

/** `?a=1&b=2`, dropping empty values; "" when nothing is set. */
export function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
