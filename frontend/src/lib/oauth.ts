/**
 * Completing a GitHub sign-in on /auth/callback.
 *
 * WHY THIS IS NOT JUST AN EFFECT. The callback page used to guard its effect with a
 * `started` ref (so the single-use code was exchanged once) and ignore results after
 * cleanup (an `active` flag). Under React Strict Mode the effect runs, is cleaned up,
 * and runs again: run 1 started the only exchange, cleanup set `active = false`, and
 * run 2 returned early because of the ref. The exchange succeeded and nobody was
 * listening, so the page sat on "Completing sign-in..." forever - and a failure was
 * swallowed the same way.
 *
 * So the exchange lives here, outside React: one promise per callback URL, shared by
 * however many times the effect runs or the component remounts. Exactly one request
 * reaches the backend; every subscriber hears the outcome; the last one mounted acts.
 */

import { ApiError, api } from "@/lib/api";
import { clearSession, storeTokens, takeOAuthState } from "@/lib/tokens";

export const CALLBACK_TIMEOUT_MS = 20_000;

/** A failure with a short message safe to show anyone. */
export class SignInError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SignInError";
  }
}

const exchanges = new Map<string, Promise<void>>();

/** Test hook: forget completed exchanges between test cases. */
export function resetExchangesForTests() {
  exchanges.clear();
}

async function exchange(params: URLSearchParams, reload: () => Promise<void>) {
  const denied = params.get("error");
  if (denied) {
    throw new SignInError(
      denied === "access_denied" ? "Sign-in was cancelled on GitHub." : "GitHub could not complete the sign-in.",
    );
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    throw new SignInError("This sign-in link is incomplete.");
  }

  // Single-use. The backend verifies the signature too; this additionally proves
  // the response came back to the tab that started it.
  const expected = takeOAuthState();
  if (expected && expected !== state) {
    throw new SignInError("This sign-in link was started in another tab or has expired.");
  }

  let result;
  try {
    result = await api.completeGitHubLogin(code, state);
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      throw new SignInError("Could not reach CodeSage. Check your connection and try again.");
    }
    // A 400 here is a stale or reused code, or an expired state. The detail text is
    // GitHub's and stays out of the page.
    throw new SignInError("GitHub did not accept this sign-in. It may have expired.");
  }

  // A fresh session: nothing from a previous account (its chosen workspace above
  // all) may leak into this one.
  clearSession();
  storeTokens(result.access, result.refresh);
  await reload();
}

/**
 * Exchange this callback's code exactly once, however often it is asked, and fail
 * with a SignInError after `timeoutMs` rather than leaving the caller waiting.
 */
export function completeSignIn(
  params: URLSearchParams,
  reload: () => Promise<void>,
  timeoutMs = CALLBACK_TIMEOUT_MS,
): Promise<void> {
  const key = params.toString();
  let pending = exchanges.get(key);
  if (!pending) {
    pending = exchange(params, reload);
    exchanges.set(key, pending);
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new SignInError("Signing in is taking too long. Please try again.")),
      timeoutMs,
    );
  });
  return Promise.race([pending, timeout]).finally(() => clearTimeout(timer));
}

/** The message to show for any failure: ours if it is ours, a generic one if not. */
export function signInMessage(err: unknown) {
  return err instanceof SignInError ? err.message : "Sign-in could not be completed.";
}
