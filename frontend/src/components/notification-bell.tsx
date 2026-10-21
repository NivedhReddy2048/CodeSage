"use client";

import { Bell, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ReviewRef } from "@/components/review-ref";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { AppNotification } from "@/lib/types";
import { cn } from "@/lib/utils";

export const NOTIFICATION_POLL_MS = 60_000;

const KIND_ICON = {
  "review.finished": { icon: CircleCheck, tone: "text-status-ok" },
  "review.degraded": { icon: TriangleAlert, tone: "text-status-degraded" },
  "review.failed": { icon: CircleX, tone: "text-status-blocking" },
  "indexing.failed": { icon: CircleX, tone: "text-status-blocking" },
} as const;

/**
 * The bell: unread count on the button (in its accessible name, not only the dot),
 * the latest notifications in a menu, and mark-as-read on open or all at once. It
 * polls once a minute and again whenever it is opened, so the count is fresh without
 * holding a second socket open.
 */
/**
 * The title with the repository's full name, for the tooltip: titles shorten it
 * ("codesage-testbed #7 · 1 blocking") so the PR number is never what gets cut.
 */
export function fullTitle(item: AppNotification) {
  const repository = item.meta?.repository;
  const number = item.meta?.pr_number;
  if (!repository || number === undefined) return item.title;
  const at = item.title.indexOf(` #${number}`);
  return at === -1 ? item.title : `${repository}${item.title.slice(at)}`;
}

export function NotificationBell() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);

  const load = useCallback(() => {
    api
      .notifications()
      .then((data) => {
        setItems(data.results);
        setUnread(data.unread_count);
      })
      .catch(() => undefined); // The bell going quiet is not worth an error state.
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, NOTIFICATION_POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  function open(item: AppNotification) {
    if (item.read) return;
    setItems((current) => current.map((n) => (n.id === item.id ? { ...n, read: true } : n)));
    setUnread((count) => Math.max(0, count - 1));
    api.markNotificationRead(item.id).catch(load);
  }

  function markAll() {
    setItems((current) => current.map((n) => ({ ...n, read: true })));
    setUnread(0);
    api.markAllNotificationsRead().catch(load);
  }

  const label = unread ? `Notifications, ${unread} unread` : "Notifications";

  return (
    <DropdownMenu onOpenChange={(isOpen) => isOpen && load()}>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label={label} className="relative" />}>
        <Bell aria-hidden="true" className="size-4" />
        {unread ? (
          // Solid rose with a canvas-coloured ring, so it reads against the icon and
          // the glass bar in either theme (text 6.3:1 light, 7.3:1 dark).
          <span
            aria-hidden="true"
            className="absolute top-0.5 right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-blocking px-1 font-mono text-[0.625rem] leading-none font-semibold text-on-blocking tabular-nums ring-2 ring-canvas"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={6} className="w-[22rem] max-w-[calc(100vw-1.5rem)] p-0">
        <DropdownMenuGroup className="p-1">
          <DropdownMenuLabel className="flex items-center justify-between px-2 py-2 text-sm font-semibold text-fg">
            <span>Notifications</span>
            {unread ? (
              <span className="rounded-full border border-border-brand bg-brand-tinted px-2 py-0.5 text-xs font-medium text-brand tabular-nums">
                {unread} unread
              </span>
            ) : null}
          </DropdownMenuLabel>
          {items.length === 0 ? (
            <p className="flex flex-col items-center gap-2 px-2 py-8 text-center text-sm text-fg-secondary">
              <CircleCheck aria-hidden="true" className="size-5 text-status-ok" />
              You are all caught up.
            </p>
          ) : (
            items.slice(0, 8).map((item) => {
              const { icon: Icon, tone } = KIND_ICON[item.kind] ?? KIND_ICON["review.finished"];
              return (
                <DropdownMenuItem
                  key={item.id}
                  render={<Link href={item.link || "/"} />}
                  onClick={() => open(item)}
                  className="items-start gap-2.5 px-2 py-2.5"
                >
                  <Icon aria-hidden="true" className={cn("mt-0.5 size-4", tone)} />
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn("block truncate text-fg", !item.read && "font-semibold")}
                      title={fullTitle(item)}
                    >
                      {item.title}
                    </span>
                    <span className="block truncate text-xs text-fg-secondary">{item.body}</span>
                    {item.meta?.head_sha || item.meta?.trigger === "rerun" ? (
                      <ReviewRef sha={item.meta.head_sha ?? ""} trigger={item.meta.trigger} className="mt-0.5" />
                    ) : null}
                    <time
                      dateTime={item.created_at}
                      className="mt-0.5 block font-mono text-[0.6875rem] text-fg-secondary tabular-nums"
                    >
                      {formatRelative(item.created_at)}
                    </time>
                  </span>
                  {!item.read ? <span className="sr-only">(unread)</span> : null}
                  {!item.read ? (
                    <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-full bg-brand ring-2 ring-brand-tinted" />
                  ) : null}
                </DropdownMenuItem>
              );
            })
          )}
        </DropdownMenuGroup>
        {unread ? (
          <>
            <DropdownMenuSeparator className="my-0" />
            <div className="p-1">
              <DropdownMenuItem onClick={markAll} className="justify-center text-sm font-medium text-brand">
                Mark all as read
              </DropdownMenuItem>
            </div>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
