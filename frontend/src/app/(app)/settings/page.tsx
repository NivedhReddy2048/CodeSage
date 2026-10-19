"use client";

import { Users } from "lucide-react";
import { useTheme } from "next-themes";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { THEME_OPTIONS } from "@/components/theme-toggle";
import { EmptyState, ErrorState, ListSkeleton, errorMessage } from "@/components/states";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import type { OrganizationRole } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROLES: OrganizationRole[] = ["owner", "admin", "member"];

function Members() {
  const { user } = useAuth();
  const { current } = useOrganization();
  const members = useResource(() => api.members(), "members");
  const [saving, setSaving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isOwner = current?.role === "owner";

  async function changeRole(membershipId: number, role: OrganizationRole) {
    setSaving(membershipId);
    setError(null);
    try {
      await api.updateMemberRole(membershipId, role);
      members.reload();
    } catch (err) {
      setError(errorMessage(err, "Could not change the role."));
    } finally {
      setSaving(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          Owners change roles; owners and admins connect repositories and re-run reviews.
          Every change is recorded in the audit log.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? <ErrorState className="mb-4" message={error} /> : null}
        {members.loading ? (
          <ListSkeleton rows={2} label="Loading members" />
        ) : members.error ? (
          <ErrorState message={members.error} onRetry={members.reload} />
        ) : members.data && members.data.length > 0 ? (
          <ul className="divide-y">
            {members.data.map((member) => {
              const name = member.user.github_login || member.user.username;
              return (
                <li key={member.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <Avatar className="size-8">
                    <AvatarImage src={member.user.avatar_url} alt="" />
                    <AvatarFallback>{name.slice(0, 2).toUpperCase()}</AvatarFallback>
                  </Avatar>
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {name}
                    {member.user.id === user?.id ? (
                      <span className="ml-1 text-xs font-normal text-muted-foreground">(you)</span>
                    ) : null}
                  </span>
                  {isOwner ? (
                    <select
                      aria-label={`Role for ${name}`}
                      value={member.role}
                      disabled={saving === member.id}
                      onChange={(event) =>
                        void changeRole(member.id, event.target.value as OrganizationRole)
                      }
                      className="h-8 rounded-md border bg-background px-2 text-sm capitalize"
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-sm capitalize text-muted-foreground">{member.role}</span>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState icon={Users} title="No members" />
        )}
      </CardContent>
    </Card>
  );
}

function Appearance() {
  const { theme, setTheme } = useTheme();
  const selected = theme ?? "system";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>System follows your operating system&apos;s light or dark setting.</CardDescription>
      </CardHeader>
      <CardContent>
        <fieldset>
          <legend className="sr-only">Theme</legend>
          <div className="grid grid-cols-3 gap-2">
            {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
              <label
                key={value}
                className={cn(
                  "flex cursor-pointer items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                  selected === value && "border-foreground bg-muted font-medium",
                )}
              >
                <input
                  type="radio"
                  name="theme"
                  value={value}
                  checked={selected === value}
                  onChange={() => setTheme(value)}
                  className="sr-only"
                />
                <Icon aria-hidden="true" className="size-4" />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { current } = useOrganization();

  return (
    <>
      <PageHeader
        title="Settings"
        description={
          current ? (
            <>
              {current.name} &middot; you are{" "}
              <span className="capitalize">{current.role ?? "a member"}</span>
            </>
          ) : undefined
        }
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Members />
        <Appearance />
      </div>
    </>
  );
}
