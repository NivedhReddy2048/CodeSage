"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { api } from "@/lib/api";
import { getSelectedOrganizationId, setSelectedOrganizationId } from "@/lib/tokens";
import type { Organization } from "@/lib/types";

type OrganizationState = {
  organizations: Organization[];
  current: Organization | null;
  loading: boolean;
  error: string | null;
  /** Bumped on every switch, so page content keyed on it reloads its data. */
  version: number;
  switchTo: (id: number) => void;
  /** Owner or admin of the current organisation. */
  canManage: boolean;
};

const OrganizationContext = createContext<OrganizationState | null>(null);

/**
 * The workspace switcher's state. The chosen id is stored and sent on every request
 * as X-Organization-Id; the backend honours it only for organisations the user is a
 * member of, so this is a preference, never a permission.
 */
export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!user) return;
    let active = true;

    api
      .organizations()
      .then((orgs) => {
        if (!active) return;
        const stored = getSelectedOrganizationId();
        // Fall back to the personal organisation the user owns, matching the
        // backend's own default, if nothing valid is stored.
        const fallback =
          orgs.find((org) => org.is_personal && org.role === "owner") ?? orgs[0];
        const chosen = orgs.find((org) => org.id === stored) ?? fallback;
        if (chosen) setSelectedOrganizationId(chosen.id);
        setOrganizations(orgs);
        setSelected(chosen?.id ?? null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Could not load organisations.");
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [user]);

  const switchTo = useCallback((id: number) => {
    setSelectedOrganizationId(id);
    setSelected(id);
    setVersion((value) => value + 1);
  }, []);

  const current = organizations.find((org) => org.id === selected) ?? null;
  const canManage = current?.role === "owner" || current?.role === "admin";

  return (
    <OrganizationContext.Provider
      value={{ organizations, current, loading, error, version, switchTo, canManage }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}

export function useOrganization() {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error("useOrganization must be used inside <OrganizationProvider>");
  }
  return context;
}
