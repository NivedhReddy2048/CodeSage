"use client";

import { CircleAlert, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";
import { completeSignIn, signInMessage } from "@/lib/oauth";

function Completing() {
  return (
    <div role="status" className="flex flex-col items-center gap-3 text-center">
      <LoaderCircle aria-hidden="true" className="size-6 animate-spin text-muted-foreground motion-reduce:animate-none" />
      <p className="text-sm text-muted-foreground">Completing sign-in...</p>
    </div>
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
      <div className="w-full max-w-sm text-center">
        <CircleAlert aria-hidden="true" className="mx-auto size-8 text-status-blocking" />
        <h1 className="mt-3 text-lg font-semibold">Sign-in failed</h1>
        <p role="alert" className="mt-2 text-sm text-muted-foreground">
          {error}
        </p>
        <Link href="/login" className={buttonVariants({ className: "mt-6 w-full" })}>
          Try again
        </Link>
      </div>
    );
  }

  return <Completing />;
}

export default function AuthCallbackPage() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      {/* useSearchParams needs a Suspense boundary to keep this route prerenderable. */}
      <Suspense fallback={<Completing />}>
        <CallbackHandler />
      </Suspense>
    </div>
  );
}
