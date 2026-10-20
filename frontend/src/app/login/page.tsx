import { BookOpenCheck, Boxes, Database, MessageSquareCode, Network, Radio, Server } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { ExampleReview } from "@/components/landing/example-review";
import { Inr } from "@/components/inr";
import { GitHubMark } from "@/components/landing/github-mark";
import { PipelineDiagram } from "@/components/landing/pipeline-diagram";
import { RedirectIfSignedIn } from "@/components/landing/redirect-if-signed-in";
import { SignInButton } from "@/components/landing/sign-in-button";
import { Logo } from "@/components/logo";
import { ThemeSwitch } from "@/components/theme-switch";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "CodeSage - AI code review that knows your codebase",
  description:
    "AI code review for GitHub pull requests that knows your codebase, not just the diff.",
};

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

/* Each tile is a component the code actually has. */
const ARCHITECTURE = [
  {
    icon: Server,
    title: "Django + DRF + Channels",
    body: "The API, the GitHub webhook receiver and the live-progress WebSocket, served by Daphne.",
  },
  {
    icon: Radio,
    title: "Webhook in under 10 s",
    body: "A signed delivery is verified, stored and queued, and answered 202. The review runs in a Celery worker.",
  },
  {
    icon: Network,
    title: "LangGraph pipeline",
    body: "An in-process agents package with no ORM imports. Groq first, Gemini on failure, a labelled degraded mode if neither answers.",
  },
  {
    icon: Database,
    title: "Postgres + pgvector",
    body: "Code split into chunks (Python by its AST), embedded at 1536 dimensions, and searched with full-text alongside.",
  },
  {
    icon: Boxes,
    title: "GitHub App",
    body: "Repository access per repository, through short-lived installation tokens. Sign-in is a separate OAuth app.",
  },
  {
    icon: BookOpenCheck,
    title: "Cost on every review",
    body: (
      <>
        Tokens and latency per call, with the cost estimated at paid-tier rates. It runs on
        free tiers, so actual spend is <Inr />0.
      </>
    ),
  },
];

// Finished class strings for the sign-in islands, computed here on the server so the
// client bundle carries no class merger (see SignInButton).
const SIGN_IN_LARGE = buttonVariants({ size: "lg", className: "h-10 gap-2 px-4 text-sm" });
const SIGN_IN_SMALL = buttonVariants({ size: "sm", className: "ml-1 hidden gap-1.5 sm:inline-flex" });

const NAV = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#architecture", label: "Architecture" },
  { href: "#example", label: "Example review" },
];

function GitHubLink({ className, label = "View on GitHub" }: { className?: string; label?: string }) {
  return (
    <a
      href={REPOSITORY_URL}
      target="_blank"
      rel="noreferrer"
      className={cn(buttonVariants({ variant: "ghost", size: "sm" }), className)}
    >
      <GitHubMark className="size-4" />
      {label}
    </a>
  );
}

function SectionHeading({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8 max-w-2xl">
      <p className="text-xs font-semibold tracking-[0.08em] text-brand uppercase">{eyebrow}</p>
      <h2 id={id} className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-fg sm:text-[1.75rem]">
        {title}
      </h2>
      <p className="mt-3 text-fg-secondary">{children}</p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="relative flex flex-1 flex-col bg-canvas">
      <RedirectIfSignedIn />

      <header className="sticky top-0 z-20 border-b border-border-subtle bg-glass backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-2 px-4 sm:px-6">
          <Logo size={26} priority className="shrink-0" />
          <nav aria-label="Page sections" className="ml-6 hidden items-center gap-1 lg:flex">
            {NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="rounded-md px-2.5 py-1.5 text-sm whitespace-nowrap text-fg-secondary transition-colors hover:bg-surface-2 hover:text-fg"
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <GitHubLink className="hidden sm:inline-flex" />
            <ThemeSwitch className="mx-1" />
            <SignInButton
              buttonClassName={SIGN_IN_SMALL}
              iconClassName="size-3.5"
              // Floats under the header, so a failure here is still seen.
              alertClassName="absolute top-full right-4 w-72 max-w-[calc(100vw-2rem)] shadow-popover sm:right-6"
            />
          </div>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-clip">
          {/* A faint grid and a mint glow, both decorative. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 [background-image:linear-gradient(var(--border-subtle)_1px,transparent_1px),linear-gradient(90deg,var(--border-subtle)_1px,transparent_1px)] [background-size:48px_48px] [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_70%)] opacity-60"
          />
          {/* Three cells: the pitch, the sign-in card, the features. On a phone they
              stack in that order, so signing in is one screen down, not three; on
              desktop the card spans both rows on the right. */}
          <div className="relative mx-auto grid max-w-[1200px] gap-10 px-4 pt-12 pb-16 sm:px-6 lg:grid-cols-[1.25fr_1fr] lg:gap-x-16 lg:gap-y-8 lg:pt-20 lg:pb-24">
            <div className="lg:col-start-1 lg:row-start-1">
              <p className="inline-flex items-center gap-2 rounded-full border border-border-brand bg-brand-tinted px-3 py-1 text-xs font-medium text-brand">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-brand-accent" />
                Multi-agent PR review
              </p>
              <h1 className="mt-5 text-display text-fg">
                Every pull request, reviewed against{" "}
                <span className="bg-gradient-to-r from-brand to-brand-accent bg-clip-text text-transparent">
                  the code it lands in
                </span>
                .
              </h1>
              <p className="mt-5 max-w-xl text-lg text-fg-secondary">
                AI code review for GitHub pull requests that knows your codebase, not just the diff.
              </p>
            </div>

            <div className="relative lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-center">
              <div
                aria-hidden="true"
                className="pointer-events-none absolute -inset-10 rounded-full bg-[radial-gradient(closest-side,color-mix(in_srgb,var(--brand-accent)_22%,transparent),transparent)] blur-2xl"
              />
              <section
                aria-label="Sign in"
                className="relative rounded-2xl border bg-surface-1 p-6 shadow-popover sm:p-8"
              >
                <h2 className="text-lg font-semibold text-fg">Sign in</h2>
                <p className="mt-1 text-sm text-fg-secondary">
                  Use your GitHub account. There is nothing else to set up to look around.
                </p>

                <div className="mt-6">
                  <SignInButton buttonClassName={cn(SIGN_IN_LARGE, "w-full")} />
                </div>

                <p className="mt-6 border-t pt-4 text-xs leading-[1.55] text-fg-secondary">
                  CodeSage reads your GitHub profile to create your account. Repository access is
                  granted separately, per repository, through the CodeSage GitHub App.
                </p>
              </section>
            </div>

            <div className="lg:col-start-1 lg:row-start-2">
              <ul className="grid gap-3 sm:grid-cols-3">
                {FEATURES.map(({ icon: Icon, title, body }) => (
                  <li key={title} className="rounded-xl border bg-surface-1 p-4 shadow-card">
                    <span className="flex size-8 items-center justify-center rounded-lg border border-border-brand bg-brand-tinted text-brand">
                      <Icon aria-hidden="true" className="size-4" />
                    </span>
                    <span className="mt-3 block text-sm font-semibold text-fg">{title}</span>
                    <span className="mt-1 block text-[0.8125rem] leading-[1.5] text-fg-secondary">{body}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* Below the fold. Each Suspense boundary is hydrated as its own unit of
            work, so React yields between them instead of hydrating the whole page in
            one long task - measurably lower blocking time on a throttled phone. */}
        <Suspense>
          {/* How it works */}
          <section aria-labelledby="how-it-works-title" id="how-it-works" className="scroll-mt-20 border-t bg-surface-1/40">
            <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6 lg:py-20">
              <SectionHeading id="how-it-works-title" eyebrow="How it works" title="One diff in, one review out">
                Diff/Intent reads the change first. Four agents then run in parallel, and
                synthesis merges what they found into a single comment on the pull request.
              </SectionHeading>
              <PipelineDiagram />
            </div>
          </section>

          {/* Architecture */}
          <section aria-labelledby="architecture-title" id="architecture" className="scroll-mt-20 border-t">
            <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6 lg:py-20">
              <SectionHeading id="architecture-title" eyebrow="Architecture" title="What it is built from">
                A Django backend and a Next.js frontend, with the review pipeline as a plain
                Python package inside the backend.
              </SectionHeading>
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {ARCHITECTURE.map(({ icon: Icon, title, body }) => (
                  <li key={title} className="rounded-xl border bg-surface-1 p-5 shadow-card">
                    <Icon aria-hidden="true" className="size-5 text-brand" />
                    <h3 className="mt-3 text-h2 text-fg">{title}</h3>
                    <p className="mt-1.5 text-sm text-fg-secondary">{body}</p>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* Example review */}
          <section aria-labelledby="example-title" id="example" className="scroll-mt-20 border-t bg-surface-1/40">
            <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6 lg:py-20">
              <SectionHeading id="example-title" eyebrow="Example review" title="What a finding looks like">
                Sample data, drawn by the same components as the review page. The blocking
                finding cites the existing code it compares against.
              </SectionHeading>
              <ExampleReview />
            </div>
          </section>

          {/* Closing call to action */}
          <section aria-labelledby="cta-title" className="border-t">
            <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6">
              <div className="relative overflow-clip rounded-2xl border border-border-brand bg-brand-deep px-6 py-10 text-center sm:px-10">
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-x-0 -top-24 mx-auto h-48 max-w-lg rounded-full bg-[radial-gradient(closest-side,color-mix(in_srgb,var(--brand-accent)_25%,transparent),transparent)] blur-2xl"
                />
                <h2 id="cta-title" className="relative text-2xl font-semibold tracking-[-0.02em] text-fg">
                  Try it on your next pull request
                </h2>
                <p className="relative mx-auto mt-2 max-w-md text-fg-secondary">
                  Sign in with GitHub, connect a repository, and open a pull request.
                </p>
                <div className="relative mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <div className="flex flex-col items-center">
                    <SignInButton buttonClassName={SIGN_IN_LARGE} />
                  </div>
                  <a
                    href={REPOSITORY_URL}
                    target="_blank"
                    rel="noreferrer"
                    className={buttonVariants({ variant: "outline", size: "lg", className: "h-10 gap-2 px-4" })}
                  >
                    <GitHubMark className="size-4" />
                    View on GitHub
                  </a>
                </div>
              </div>
            </div>
          </section>
        </Suspense>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-8 sm:flex-row sm:items-center sm:px-6">
          <Logo size={22} />
          <p className="text-sm text-fg-secondary sm:ml-4">Multi-agent code review for GitHub pull requests.</p>
          <div className="flex items-center gap-1 sm:ml-auto">
            <GitHubLink />
          </div>
        </div>
      </footer>
    </div>
  );
}
