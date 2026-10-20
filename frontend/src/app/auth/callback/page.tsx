"use client";

import { CircleAlert, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/logo";
import { buttonVariants } from "@/components/ui/button";
import { completeSignIn, signInMessage } from "@/lib/oauth";

/** The card both states sit in: the mark, then the content. Presentation only. */
function CallbackCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative w-full max-w-sm">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -inset-8 rounded-full bg-[radial-gradient(closest-side,color-mix(in_srgb,var(--brand-accent)_18%,transparent),transparent)] blur-2xl"
      />
      <div className="relative rounded-2xl border bg-surface-1 px-6 py-8 text-center shadow-popover">
        <Logo markOnly size={40} className="justify-center" />
        {children}
      </div>
    </div>
  );
}

function Completing() {
  return (
    <CallbackCard>
      <div role="status" className="mt-5 flex flex-col items-center gap-3">
        <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-brand motion-reduce:animate-none" />
        <p className="text-sm text-fg-secondary">Completing sign-in...</p>
      </div>
    </CallbackCard>
  );
}

function CallbackHandler() {
  const router = useRouter();
  const params = useSearchParams();
  const { reload } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // No "already started" guard here: that guard, combined with ignoring results
    // after cleanup, is what hung this page under Strict Mode. Every run subscribes
    // to the same single exchange (see lib/oauth.ts); only the live one acts on it.
    let active = true;

    completeSignIn(new URLSearchParams(params.toString()), reload)
      .then(() => {
        if (active) router.replace("/");
      })
      .catch((err: unknown) => {
        if (active) setError(signInMessage(err));
      });

    return () => {
      active = false;
    };
  }, [params, reload, router]);

  if (error) {
    return (
      <CallbackCard>
        <h1 className="mt-5 flex items-center justify-center gap-2 text-lg font-semibold text-fg">
          <CircleAlert aria-hidden="true" className="size-5 text-status-blocking" />
          Sign-in failed
        </h1>
        <p
          role="alert"
          className="mt-3 rounded-lg border border-status-blocking-border bg-status-blocking-bg px-3 py-2 text-sm text-status-blocking"
        >
          {error}
        </p>
        <Link href="/login" className={buttonVariants({ className: "mt-6 h-10 w-full" })}>
          Try again
        </Link>
      </CallbackCard>
    );
  }

  return <Completing />;
}

export default function AuthCallbackPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-canvas px-4 py-16">
      {/* useSearchParams needs a Suspense boundary to keep this route prerenderable. */}
      <Suspense fallback={<Completing />}>
        <CallbackHandler />
      </Suspense>
    </div>
  );
}
