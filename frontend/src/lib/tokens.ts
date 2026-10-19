/**
 * JWT storage.
 *
 * localStorage is used rather than cookies because the backend is on a different
 * origin (Render vs Vercel) and issues bearer tokens, so there is no same-site cookie
 * to lean on. The tradeoff is honest: tokens in localStorage are readable by any
 * script that gets injected into the page. The access token is deliberately
 * short-lived (30 minutes) to limit the window.
 *
 * Every accessor tolerates storage being unavailable — Safari private mode and
 * blocked site data both throw on access rather than returning null.
 */

const ACCESS_KEY = "codesage.access";
const REFRESH_KEY = "codesage.refresh";
const OAUTH_STATE_KEY = "codesage.oauth_state";
const ORGANIZATION_KEY = "codesage.organization";

function readLocal(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLocal(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Non-fatal: the user stays signed in for this page load only.
  }
}

function removeLocal(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing to do.
  }
}

export function getAccessToken() {
  return readLocal(ACCESS_KEY);
}

export function getRefreshToken() {
  return readLocal(REFRESH_KEY);
}

export function storeTokens(access: string, refresh: string) {
  writeLocal(ACCESS_KEY, access);
  writeLocal(REFRESH_KEY, refresh);
}

export function clearTokens() {
  removeLocal(ACCESS_KEY);
  removeLocal(REFRESH_KEY);
  removeLocal(ORGANIZATION_KEY);
}

/**
 * The workspace chosen in the org switcher, sent as X-Organization-Id. Only a
 * preference: the backend honours it solely for organisations the user belongs to.
 */
export function getSelectedOrganizationId(): number | null {
  const value = Number(readLocal(ORGANIZATION_KEY));
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function setSelectedOrganizationId(id: number) {
  writeLocal(ORGANIZATION_KEY, String(id));
}

/**
 * The OAuth `state` nonce lives in sessionStorage, not localStorage: it is valid for
 * exactly one login attempt in one tab, and should not outlive the browser session.
 */
export function storeOAuthState(state: string) {
  try {
    window.sessionStorage.setItem(OAUTH_STATE_KEY, state);
  } catch {
    // If this fails the callback's client-side check is skipped, but the backend
    // still verifies the signature, so the flow degrades rather than breaking.
  }
}

export function takeOAuthState(): string | null {
  try {
    const state = window.sessionStorage.getItem(OAUTH_STATE_KEY);
    // Single use: remove it whether or not it matches, so a code cannot be replayed.
    window.sessionStorage.removeItem(OAUTH_STATE_KEY);
    return state;
  } catch {
    return null;
  }
}
