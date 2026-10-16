"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth-provider";
import { api } from "@/lib/api";
import { storeOAuthState } from "@/lib/tokens";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in: don't show a login page behind a valid session.
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

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
      setError(err instanceof Error ? err.message : "Could not start sign-in.");
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">CodeSage</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Multi-agent code review for your pull requests.
          </p>
        </div>

        <Button
          className="w-full"
          onClick={signIn}
          disabled={starting || loading}
        >
          {starting ? "Redirecting to GitHub..." : "Continue with GitHub"}
        </Button>

        {error ? (
          <p
            role="alert"
            className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <p className="mt-6 text-center text-xs text-muted-foreground">
          CodeSage reads your GitHub profile to create your account. Repository access
          is granted separately, per repository.
        </p>
      </div>
    </div>
  );
}
