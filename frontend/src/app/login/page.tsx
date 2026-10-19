"use client";

import { BookOpenCheck, MessageSquareCode, Network } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { storeOAuthState } from "@/lib/tokens";

export const REPOSITORY_URL = "https://github.com/NivedhReddy2048/CodeSage";

const FEATURES = [
  {
    icon: Network,
    title: "Multi-agent review",
    body: "Five agents read every pull request: intent, security, static analysis, test coverage and codebase grounding.",
  },
  {
    icon: BookOpenCheck,
    title: "Grounded in your codebase",
    body: "Findings cite the existing code they rest on, and a citation that does not support the claim is dropped.",
  },
  {
    icon: MessageSquareCode,
    title: "Inline PR comments",
    body: "Each finding lands on its line in GitHub's Files changed tab, deduplicated across re-reviews.",
  },
];

/** The GitHub mark (Octicons, MIT). Lucide no longer ships brand icons. */
function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

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
      setError(
        err instanceof ApiError && err.status === 0
          ? "Could not reach CodeSage. Check your connection and try again."
          : "Could not start sign-in. Please try again.",
      );
      setStarting(false);
    }
  }

  return (
    <div className="relative flex flex-1 flex-col bg-gradient-to-b from-muted/60 to-background">
      <header className="flex items-center justify-end gap-1 px-4 py-3">
        <a
          href={REPOSITORY_URL}
          target="_blank"
          rel="noreferrer"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <GitHubMark className="size-4" />
          View on GitHub
        </a>
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="grid w-full max-w-4xl items-center gap-10 md:grid-cols-[1.1fr_1fr] md:gap-14">
          <section aria-labelledby="product" className="text-center md:text-left">
            <Image
              src="/codesage-logo.png"
              alt="CodeSage logo"
              width={64}
              height={64}
              priority
              className="mx-auto rounded-2xl shadow-sm ring-1 ring-foreground/10 md:mx-0"
            />
            <h1 id="product" className="mt-5 text-3xl font-semibold tracking-tight sm:text-4xl">
              CodeSage
            </h1>
            <p className="mt-3 text-lg text-muted-foreground">
              AI code review for GitHub pull requests that knows your codebase, not just the diff.
            </p>
            <ul className="mt-8 space-y-5 text-left">
              {FEATURES.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-status-ok-bg text-status-ok">
                    <Icon aria-hidden="true" className="size-4.5" />
                  </span>
                  <span>
                    <span className="block font-medium">{title}</span>
                    <span className="block text-sm text-muted-foreground">{body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section
            aria-label="Sign in"
            className="rounded-2xl border bg-card p-6 shadow-sm sm:p-8"
          >
            <h2 className="text-lg font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Use your GitHub account. There is nothing else to set up to look around.
            </p>

            <Button className="mt-6 h-10 w-full gap-2" onClick={signIn} disabled={starting || loading}>
              <GitHubMark className="size-4" />
              {starting ? "Redirecting to GitHub..." : "Continue with GitHub"}
            </Button>

            {error ? (
              <p
                role="alert"
                className="mt-4 rounded-md border border-status-blocking/30 bg-status-blocking-bg px-3 py-2 text-sm text-status-blocking"
              >
                {error}
              </p>
            ) : null}

            <p className="mt-6 text-xs text-muted-foreground">
              CodeSage reads your GitHub profile to create your account. Repository access is
              granted separately, per repository, through the CodeSage GitHub App.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
