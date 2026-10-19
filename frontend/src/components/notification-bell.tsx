"use client";

import { Bell, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-blocking px-1 text-[10px] font-semibold text-background"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center justify-between">
            <span>Notifications</span>
            {unread ? <span className="font-normal">{unread} unread</span> : null}
          </DropdownMenuLabel>
          {items.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">You are all caught up.</p>
          ) : (
            items.slice(0, 8).map((item) => {
              const { icon: Icon, tone } = KIND_ICON[item.kind] ?? KIND_ICON["review.finished"];
              return (
                <DropdownMenuItem
                  key={item.id}
                  render={<Link href={item.link || "/"} />}
                  onClick={() => open(item)}
                  className="items-start gap-2 py-2"
                >
                  <Icon aria-hidden="true" className={cn("mt-0.5 size-4", tone)} />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate", !item.read && "font-semibold")}>
                      {item.title}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {item.body} · {formatRelative(item.created_at)}
                    </span>
                  </span>
                  {!item.read ? <span className="sr-only">(unread)</span> : null}
                  {!item.read ? (
                    <span aria-hidden="true" className="mt-1.5 size-2 rounded-full bg-status-running" />
                  ) : null}
                </DropdownMenuItem>
              );
            })
          )}
        </DropdownMenuGroup>
        {unread ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={markAll} className="justify-center text-sm">
              Mark all as read
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
