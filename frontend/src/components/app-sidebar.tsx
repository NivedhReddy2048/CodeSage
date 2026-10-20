"use client";

import {
  Check,
  ChevronsUpDown,
  FolderGit2,
  GitPullRequest,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/logo";
import { useOrganization } from "@/components/organization-provider";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/repos", label: "Repositories", icon: FolderGit2 },
  { href: "/reviews", label: "Reviews", icon: GitPullRequest },
  { href: "/audit", label: "Audit log", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function isActivePath(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function initials(name: string) {
  return name.slice(0, 2).toUpperCase();
}

/** A workspace's badge: its initial on the brand tint, sized for the rail. */
function WorkspaceBadge({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg border border-border-brand bg-brand-tinted font-mono text-sm font-semibold text-brand uppercase",
        className,
      )}
    >
      {name.slice(0, 1) || "?"}
    </span>
  );
}

function roleLine(org: { role?: string | null; is_personal: boolean }) {
  return `${org.role ?? "member"}${org.is_personal ? " · personal" : ""}`;
}

function OrganizationSwitcher() {
  const { organizations, current, loading, switchTo } = useOrganization();
  const { state, isMobile } = useSidebar();
  // From the icon rail there is no room below, so the menu opens beside it.
  const beside = state === "collapsed" && !isMobile;

  if (loading) return <SidebarMenuSkeleton showIcon />;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <SidebarMenuButton
            size="lg"
            aria-label={`Organisation: ${current?.name ?? "none"}. Switch organisation`}
          />
        }
      >
        <WorkspaceBadge name={current?.name ?? ""} />
        <span className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
          <span className="truncate font-medium text-fg">{current?.name ?? "No organisation"}</span>
          <span className="truncate text-xs text-fg-secondary capitalize">
            {current ? roleLine(current) : ""}
          </span>
        </span>
        <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
      </DropdownMenuTrigger>
      {/* A floating layer: wider than the sidebar so it visibly sits above it, on
          surface-3 with the popover shadow, rather than a same-coloured panel that
          read as part of the nav laid over "Dashboard". */}
      <DropdownMenuContent
        className="w-64"
        side={beside ? "right" : "bottom"}
        align="start"
        sideOffset={beside ? 10 : 6}
      >
        <DropdownMenuGroup>
          <DropdownMenuLabel>Organisations</DropdownMenuLabel>
          {organizations.map((org) => (
            <DropdownMenuItem key={org.id} onClick={() => switchTo(org.id)} className="gap-2.5 py-1.5">
              <WorkspaceBadge name={org.name} className="size-7 text-xs" />
              <span className="grid min-w-0 flex-1 leading-tight">
                <span className="truncate font-medium">{org.name}</span>
                <span className="truncate text-xs text-fg-secondary capitalize">{roleLine(org)}</span>
              </span>
              {org.id === current?.id ? (
                <Check aria-label="Current organisation" className="size-4 text-brand" />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  if (!user) return null;
  const name = user.github_login || user.username;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<SidebarMenuButton size="lg" aria-label={`Account: ${name}`} />}
      >
        <Avatar className="size-8">
          <AvatarImage src={user.avatar_url} alt="" />
          <AvatarFallback>{initials(name)}</AvatarFallback>
        </Avatar>
        <span className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
          <span className="truncate font-medium text-fg">{name}</span>
          <span className="truncate text-xs text-fg-secondary">
            {user.email || "No public email"}
          </span>
        </span>
        <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60" side="top" align="start" sideOffset={6}>
        <DropdownMenuItem render={<Link href="/settings" />}>
          <Settings aria-hidden="true" />
          Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={signOut}>
          <LogOut aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon" aria-label="Main navigation">
      <SidebarHeader className="gap-3">
        <Link
          href="/"
          aria-label="CodeSage, dashboard"
          className="flex h-10 items-center rounded-lg px-2 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
        >
          <Logo size={28} wordmarkClassName="group-data-[collapsible=icon]:hidden" />
        </Link>
        <SidebarMenu>
          <SidebarMenuItem>
            <OrganizationSwitcher />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <nav aria-label="Primary">
              <SidebarMenu>
                {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
                  const active = isActivePath(pathname, href);
                  return (
                    <SidebarMenuItem key={href}>
                      <SidebarMenuButton
                        isActive={active}
                        tooltip={label}
                        render={
                          <Link href={href} aria-current={active ? "page" : undefined} />
                        }
                      >
                        <Icon aria-hidden="true" />
                        <span>{label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </nav>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <UserMenu />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
