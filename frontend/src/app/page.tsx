"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/components/auth-provider";
import { api } from "@/lib/api";
import type { Organization } from "@/lib/types";

/**
 * Phase 1 authenticated shell. Its job is to prove the token works end to end:
 * the real dashboard, sidebar and org switcher arrive in phase 6 (spec section 9).
 */
export default function HomePage() {
  const router = useRouter();
  const { user, loading, signOut } = useAuth();

  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [orgsError, setOrgsError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    void (async () => {
      try {
        setOrgs(await api.organizations());
      } catch (err) {
        setOrgsError(
          err instanceof Error ? err.message : "Could not load organisations.",
        );
      }
    })();
  }, [user]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-12">
      <header className="mb-8 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Avatar>
            <AvatarImage src={user.avatar_url} alt="" />
            <AvatarFallback>
              {(user.github_login || user.username).slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="truncate font-medium">{user.github_login}</p>
            <p className="truncate text-sm text-muted-foreground">
              {user.email || "No public email"}
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={signOut}>
          Sign out
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Your organisations</CardTitle>
          <CardDescription>
            Repositories and reviews belong to an organisation, never directly to a
            user.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {orgsError ? (
            <p role="alert" className="text-sm text-destructive">
              {orgsError}
            </p>
          ) : orgs === null ? (
            <p className="text-sm text-muted-foreground">Loading organisations...</p>
          ) : orgs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No organisations yet.</p>
          ) : (
            <ul className="divide-y">
              {orgs.map((org) => (
                <li
                  key={org.id}
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{org.name}</p>
                    <p className="truncate text-sm text-muted-foreground">
                      {org.slug}
                      {org.is_personal ? " · personal" : ""}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs capitalize text-muted-foreground">
                    {org.role}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        Phase 1 of 8. Connecting repositories comes next.
      </p>
    </div>
  );
}
