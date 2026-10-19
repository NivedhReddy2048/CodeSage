"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export type Resource<T> = {
  data: T | null;
  error: string | null;
  /** HTTP status of the failure, so a page can tell 403 from "API down". */
  status: number | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Load something once per change of `key`, with a stale-response guard and a retry.
 *
 * State is only ever set inside promise callbacks, never synchronously in the effect
 * body, which is what the React Compiler lint rules require.
 */
export function useResource<T>(load: () => Promise<T>, key: string): Resource<T> {
  const [state, setState] = useState<{
    data: T | null;
    error: string | null;
    status: number | null;
    settledKey: string | null;
  }>({ data: null, error: null, status: null, settledKey: null });
  const [attempt, setAttempt] = useState(0);

  // `load` is a new closure every render; `key` is what decides when to refetch.
  // The latest closure is kept in a ref (written in a layout effect, which runs
  // before the fetching effect) so the fetch always uses current arguments.
  const loadRef = useRef(load);
  useLayoutEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    let active = true;
    const settledKey = `${key}#${attempt}`;
    loadRef.current()
      .then((data) => {
        if (active) setState({ data, error: null, status: null, settledKey });
      })
      .catch((err: unknown) => {
        if (!active) return;
        setState({
          data: null,
          error: err instanceof Error ? err.message : "Something went wrong.",
          status: err instanceof ApiError ? err.status : null,
          settledKey,
        });
      });
    return () => {
      active = false;
    };
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    data: state.data,
    error: state.error,
    status: state.status,
    loading: state.settledKey !== `${key}#${attempt}`,
    reload,
  };
}
