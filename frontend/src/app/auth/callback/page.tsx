"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";
import { api } from "@/lib/api";
import { storeTokens, takeOAuthState } from "@/lib/tokens";

/**
 * Validate the callback parameters and exchange the code for tokens.
 *
 * All of it lives in one async function so the caller only ever updates state from a
 * promise callback — updating state synchronously inside an effect body causes
 * cascading renders, and the lint rules reject it.
 */
async function completeLogin(params: URLSearchParams, reload: () => Promise<void>) {
  const denied = params.get("error");
  if (denied) {
    throw new Error(
      denied === "access_denied"
        ? "Sign-in was cancelled on GitHub."
        : `GitHub returned an error: ${denied}`,
    );
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    throw new Error("This callback URL is missing its code or state parameter.");
  }

  // Single-use, and cleared on read. The backend verifies the signature too; this
  // check additionally proves the response came back to the tab that started it.
  const expected = takeOAuthState();
  if (expected && expected !== state) {
    throw new Error("Sign-in state did not match. Please start again.");
  }

  const result = await api.completeGitHubLogin(code, state);
  storeTokens(result.access, result.refresh);
  await reload();
}

function CallbackHandler() {
  const router = useRouter();
  const params = useSearchParams();
  const { reload } = useAuth();
  const [error, setError] = useState<string | null>(null);

  // React runs effects twice in development Strict Mode, and an OAuth code is
  // single-use — exchanging it twice fails the second time with a confusing error.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    let active = true;

    completeLogin(new URLSearchParams(params.toString()), reload)
      .then(() => {
        if (active) router.replace("/");
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Sign-in failed.");
      });

    return () => {
      active = false;
    };
  }, [params, reload, router]);

  if (error) {
    return (
      <div className="w-full max-w-sm text-center">
        <h1 className="text-lg font-semibold">Sign-in failed</h1>
        <p
          role="alert"
          className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
        {/* A styled Link rather than <Button render>: this is a navigation, so the
            rendered element should be an anchor. */}
        <Link
          href="/login"
          className={buttonVariants({ className: "mt-6 w-full" })}
        >
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="text-center">
      <p className="text-sm text-muted-foreground">Completing sign-in...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      {/* useSearchParams needs a Suspense boundary to keep this route prerenderable. */}
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">Completing sign-in...</p>
        }
      >
        <CallbackHandler />
      </Suspense>
    </div>
  );
}
