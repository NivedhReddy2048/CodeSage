"use client";

import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { GitHubMark } from "@/components/landing/github-mark";
import { ApiError, api } from "@/lib/api";
import { storeOAuthState } from "@/lib/tokens";

/**
 * "Continue with GitHub". The landing page has several - header, hero card, closing
 * band - and each one is this island with its own state, so a failure is reported
 * next to the button that was pressed rather than somewhere off screen.
 *
 * The flow itself is unchanged: ask the API for GitHub's authorize URL, store the
 * OAuth state for the callback to verify, then leave for GitHub.
 *
 * Its classes arrive as finished strings, computed by the server page with
 * `buttonVariants`: this island imports no class merger, variant library or
 * component library, which kept ~35 KB of script off the landing page.
 */
export function SignInButton({
  buttonClassName,
  iconClassName = "size-4",
  alertClassName = "",
}: {
  buttonClassName: string;
  iconClassName?: string;
  alertClassName?: string;
}) {
  const { loading } = useAuth();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    setStarting(true);
    setError(null);
    try {
      const { authorize_url, state } = await api.startGitHubLogin();
      // Stored before navigating away, so the callback can verify GitHub echoed
      // back the same state we sent.
      storeOAuthState(state);
      window.location.href = authorize_url;
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 0
          ? "Could not reach CodeSage. Check your connection and try again."
          : "Could not start sign-in. Please try again.",
      );
      setStarting(false);
    }
  }

  return (
    <>
      <button type="button" className={buttonClassName} onClick={signIn} disabled={starting || loading}>
        <GitHubMark className={iconClassName} />
        {starting ? "Redirecting to GitHub..." : "Continue with GitHub"}
      </button>
      {error ? (
        <p
          role="alert"
          className={`mt-3 rounded-lg border border-status-blocking-border bg-status-blocking-bg px-3 py-2 text-sm text-status-blocking ${alertClassName}`}
        >
          {error}
        </p>
      ) : null}
    </>
  );
}
