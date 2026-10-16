"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/tokens";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  /** True until the stored token has been checked, so pages can avoid flashing. */
  loading: boolean;
  signOut: () => void;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

/**
 * Resolve the signed-in user from the stored token, or null when there isn't one.
 *
 * Deliberately a module-level async function rather than inline effect logic: it
 * guarantees every caller gets a Promise, so state updates always land in a `.then`
 * callback instead of running synchronously inside an effect body.
 */
async function fetchCurrentUser(): Promise<User | null> {
  // No token at all: skip the request entirely, it could only 401.
  if (!getAccessToken()) return null;
  return api.currentUser();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    fetchCurrentUser()
      .then((nextUser) => {
        if (!active) return;
        setUser(nextUser);
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        // Expired or revoked. The API client already tried to refresh, so drop the
        // tokens rather than leaving the app half signed in.
        clearTokens();
        setUser(null);
        setLoading(false);
      });

    // Guards against a late response overwriting state after unmount.
    return () => {
      active = false;
    };
  }, []);

  /** Re-read the current user. Called after a successful login, not from an effect. */
  const reload = useCallback(async () => {
    try {
      setUser(await fetchCurrentUser());
    } catch {
      clearTokens();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signOut, reload }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
