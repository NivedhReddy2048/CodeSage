"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { clearSession, clearTokens, getAccessToken } from "@/lib/tokens";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  /** True until the stored token has been checked, so pages can avoid flashing. */
  loading: boolean;
  /**
   * Set when the session could not be checked for a reason other than the token
   * being rejected - the API is down, or a request was blocked. The session is kept.
   */
  error: string | null;
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
/**
 * Only a 401 means the session is over. Treating every failure that way signed
 * people out whenever the API hiccuped - and, found in a real browser, on every
 * other page load while a CORS preflight was failing.
 */
function isRejectedSession(err: unknown) {
  return err instanceof ApiError && err.status === 401;
}

async function fetchCurrentUser(): Promise<User | null> {
  // No token at all: skip the request entirely, it could only 401.
  if (!getAccessToken()) return null;
  return api.currentUser();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    fetchCurrentUser()
      .then((nextUser) => {
        if (!active) return;
        setUser(nextUser);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (isRejectedSession(err)) {
          // Expired or revoked. The API client already tried to refresh, so drop
          // the tokens rather than leaving the app half signed in.
          clearTokens();
          setError(null);
        } else {
          setError(err instanceof Error ? err.message : "Could not reach the API.");
        }
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
      setError(null);
    } catch (err) {
      if (isRejectedSession(err)) {
        clearTokens();
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : "Could not reach the API.");
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearSession();
    setUser(null);
    setError(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, error, signOut, reload }}>
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
