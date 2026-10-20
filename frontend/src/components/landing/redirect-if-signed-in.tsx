"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth-provider";

/** Already signed in: don't show the landing page behind a valid session. */
export function RedirectIfSignedIn() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  return null;
}
