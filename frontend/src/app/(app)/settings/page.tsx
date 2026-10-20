"use client";

import { Check, Minus, ShieldCheck, Users } from "lucide-react";
import { useTheme } from "next-themes";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { THEME_OPTIONS } from "@/components/theme-toggle-options";
import { EmptyState, ErrorState, ListSkeleton, errorMessage } from "@/components/states";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
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

  async function changeRole(membershipId: number, name: string, role: OrganizationRole) {
    setSaving(membershipId);
    setError(null);
    try {
      await api.updateMemberRole(membershipId, role);
      members.reload();
      toast.success(`${name} is now ${role === "admin" ? "an" : "a"} ${role}`);
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
                  <Avatar className="size-9">
                    <AvatarImage src={member.user.avatar_url} alt="" />
                    <AvatarFallback>{name.slice(0, 2).toUpperCase()}</AvatarFallback>
                  </Avatar>
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-[0.8125rem] font-medium text-fg">{name}</span>
                      {member.user.id === user?.id ? (
                        <span className="shrink-0 rounded-full border border-border-brand bg-brand-tinted px-1.5 text-[0.6875rem] font-medium text-brand">
                          you
                        </span>
                      ) : null}
                    </span>
                    <span className="block text-xs text-fg-secondary capitalize">{member.role}</span>
                  </span>
                  {isOwner ? (
                    <NativeSelect
                      aria-label={`Role for ${name}`}
                      value={member.role}
                      disabled={saving === member.id}
                      onChange={(event) =>
                        void changeRole(member.id, name, event.target.value as OrganizationRole)
                      }
                      className="capitalize"
                      wrapperClassName="w-28"
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </NativeSelect>
                  ) : (
                    <span className="rounded-md border bg-surface-2 px-2 py-0.5 text-xs font-medium text-fg-secondary capitalize">
                      {member.role}
                    </span>
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

/*
 * Who can do what, as the backend enforces it:
 * - members: everything org-scoped is readable (accounts, repos, reviews, analytics);
 * - owner or admin (REPO_MANAGEMENT_ROLES): connect, disconnect, re-index, re-run,
 *   read the audit log, and see raw error text;
 * - owner only: change roles (accounts/views.py), and the last owner cannot be
 *   demoted.
 * Keep these rows in step with those checks.
 */
const PERMISSIONS: { action: string; owner: boolean; admin: boolean; member: boolean }[] = [
  { action: "See the dashboard, repositories, reviews and notifications", owner: true, admin: true, member: true },
  { action: "Connect and disconnect repositories", owner: true, admin: true, member: false },
  { action: "Re-index a repository", owner: true, admin: true, member: false },
  { action: "Re-run a review", owner: true, admin: true, member: false },
  { action: "Read the audit log", owner: true, admin: true, member: false },
  { action: "See raw error details", owner: true, admin: true, member: false },
  { action: "Change members' roles", owner: true, admin: false, member: false },
];

function Allowed({ allowed }: { allowed: boolean }) {
  return allowed ? (
    <span className="inline-flex size-6 items-center justify-center rounded-full bg-status-ok-bg text-status-ok">
      <Check aria-hidden="true" className="size-3.5" />
      <span className="sr-only">Allowed</span>
    </span>
  ) : (
    <span className="inline-flex size-6 items-center justify-center text-fg-secondary">
      <Minus aria-hidden="true" className="size-3.5" />
      <span className="sr-only">Not allowed</span>
    </span>
  );
}

function Permissions() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck aria-hidden="true" className="size-4 text-brand" />
          Role permissions
        </CardTitle>
        <CardDescription>
          What each role can do. The API checks every one; hiding a control is only a convenience.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-control">
            <caption className="sr-only">Permissions by role</caption>
            <thead className="bg-surface-2/60">
              <tr className="border-b">
                <th scope="col" className="px-3 py-2 text-left text-micro text-fg-secondary">
                  Action
                </th>
                {["Owner", "Admin", "Member"].map((role) => (
                  <th key={role} scope="col" className="w-16 px-2 py-2 text-center text-micro text-fg-secondary">
                    {role}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PERMISSIONS.map((row) => (
                <tr key={row.action} className="border-b last:border-0">
                  <th scope="row" className="px-3 py-2 text-left font-normal text-fg">
                    {row.action}
                  </th>
                  <td className="px-2 py-1.5 text-center">
                    <Allowed allowed={row.owner} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <Allowed allowed={row.admin} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <Allowed allowed={row.member} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-fg-secondary">
          An organisation always keeps at least one owner: the last one cannot be demoted.
        </p>
      </CardContent>
    </Card>
  );
}

/** A miniature of the app in one theme: sidebar, top bar, a card and a brand bar. */
function ThemePreview({ mode }: { mode: "light" | "dark" | "system" }) {
  const palette = {
    light: { canvas: "#f8fafc", panel: "#ffffff", line: "#e2e8f0", text: "#0f172a", muted: "#cbd5e1", brand: "#047857" },
    dark: { canvas: "#060a0f", panel: "#0b121b", line: "#1e2d3d", text: "#f1f5f9", muted: "#2e445c", brand: "#10b981" },
  };
  const half = (p: (typeof palette)["light"], clip?: string) => (
    <g clipPath={clip}>
      <rect width="160" height="96" fill={p.canvas} />
      <rect width="40" height="96" fill={p.panel} />
      <rect x="40" width="120" height="16" fill={p.panel} />
      <line x1="40" y1="0" x2="40" y2="96" stroke={p.line} />
      <line x1="40" y1="16" x2="160" y2="16" stroke={p.line} />
      <rect x="8" y="8" width="10" height="10" rx="3" fill={p.brand} />
      <rect x="8" y="28" width="24" height="4" rx="2" fill={p.text} opacity="0.8" />
      <rect x="8" y="38" width="20" height="4" rx="2" fill={p.muted} />
      <rect x="8" y="48" width="22" height="4" rx="2" fill={p.muted} />
      <rect x="50" y="26" width="100" height="58" rx="6" fill={p.panel} stroke={p.line} />
      <rect x="58" y="34" width="40" height="5" rx="2.5" fill={p.text} opacity="0.85" />
      <rect x="58" y="62" width="10" height="16" rx="2" fill={p.brand} />
      <rect x="72" y="54" width="10" height="24" rx="2" fill={p.brand} />
      <rect x="86" y="66" width="10" height="12" rx="2" fill={p.brand} opacity="0.7" />
    </g>
  );
  return (
    <svg viewBox="0 0 160 96" aria-hidden="true" className="block h-auto w-full">
      <defs>
        <clipPath id="theme-preview-half">
          <polygon points="80,0 160,0 160,96 80,96" />
        </clipPath>
      </defs>
      {mode === "dark" ? half(palette.dark) : half(palette.light)}
      {mode === "system" ? half(palette.dark, "url(#theme-preview-half)") : null}
    </svg>
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
          <div className="grid gap-3 sm:grid-cols-3">
            {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
              <label
                key={value}
                className={cn(
                  "group cursor-pointer overflow-clip rounded-xl border bg-surface-1 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus hover:border-border-strong",
                  selected === value && "border-brand ring-1 ring-brand",
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
                <span className="block border-b">
                  <ThemePreview mode={value} />
                </span>
                <span className="flex items-center gap-2 px-3 py-2.5 text-sm">
                  <Icon aria-hidden="true" className="size-4 text-fg-secondary" />
                  <span className={cn("flex-1", selected === value ? "font-medium text-fg" : "text-fg-secondary")}>
                    {label}
                  </span>
                  {selected === value ? (
                    <span className="flex size-4 items-center justify-center rounded-full bg-brand text-on-brand">
                      <Check aria-hidden="true" className="size-3" />
                    </span>
                  ) : null}
                </span>
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
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Members />
        <Permissions />
      </div>
      <div className="mt-6">
        <Appearance />
      </div>
    </>
  );
}
