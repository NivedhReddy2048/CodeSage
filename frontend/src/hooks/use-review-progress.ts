"use client";

import { useEffect, useRef, useState } from "react";

import { api, ensureFreshToken, wsUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/tokens";
import type { ReviewProgress } from "@/lib/types";

export const POLL_INTERVAL_MS = 3000;
const CLOSE_UNAUTHENTICATED = 4401;
const CLOSE_NOT_FOUND = 4404;

export type ProgressTransport = "socket" | "polling" | "idle";

export type LiveProgress = {
  progress: ReviewProgress | null;
  transport: ProgressTransport;
};

function isActive(status: string | undefined) {
  return status === "pending" || status === "running";
}

/**
 * Live pipeline progress for one review: the /ws/reviews/<id>/ socket first, and
 * the status endpoint polled every few seconds whenever the socket is unavailable
 * or drops. `onFinished` fires once when the review leaves pending/running, so the
 * page can fetch the finished review.
 *
 * The socket authenticates with the access token in its first message. A 4401
 * (token expired) gets one refresh and one reconnect; a 4404 means there is nothing
 * to watch, and stops everything.
 */
export function useReviewProgress(
  reviewId: number,
  initialStatus: string | undefined,
  onFinished: () => void,
): LiveProgress {
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [transport, setTransport] = useState<ProgressTransport>("idle");
  const finishedRef = useRef(onFinished);
  useEffect(() => {
    finishedRef.current = onFinished;
  });

  const watching = isActive(initialStatus);

  useEffect(() => {
    if (!watching) return;

    let stopped = false;
    let socket: WebSocket | null = null;
    let poller: ReturnType<typeof setInterval> | null = null;
    let refreshedOnce = false;
    let done = false;

    const finish = () => {
      if (done) return;
      done = true;
      stopAll();
      setTransport("idle");
      finishedRef.current();
    };

    const accept = (event: ReviewProgress) => {
      if (stopped) return;
      setProgress(event);
      if (event.type === "review.finished" || !isActive(event.status)) finish();
    };

    const startPolling = () => {
      if (stopped || done || poller) return;
      setTransport("polling");
      const tick = () =>
        api
          .reviewStatus(reviewId)
          .then(accept)
          .catch(() => undefined);
      tick();
      poller = setInterval(tick, POLL_INTERVAL_MS);
    };

    const connect = () => {
      if (stopped || done) return;
      try {
        socket = new WebSocket(wsUrl(`/ws/reviews/${reviewId}/`));
      } catch {
        startPolling();
        return;
      }
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: "auth", token: getAccessToken() ?? "" }));
      };
      socket.onmessage = (message) => {
        // Anything arriving after the finish (or after unmount) is stale.
        if (stopped || done) return;
        let event: ReviewProgress;
        try {
          event = JSON.parse(String(message.data)) as ReviewProgress;
        } catch {
          return; // A malformed frame is ignored; the next one carries the full state.
        }
        setTransport("socket");
        accept(event);
      };
      socket.onclose = (event) => {
        socket = null;
        if (stopped || done) return;
        if (event.code === CLOSE_NOT_FOUND) {
          stopAll();
          setTransport("idle");
          return;
        }
        if (event.code === CLOSE_UNAUTHENTICATED && !refreshedOnce) {
          refreshedOnce = true;
          ensureFreshToken().then(connect, startPolling);
          return;
        }
        // Dropped, refused, or never opened: keep the pill live by polling.
        startPolling();
      };
    };

    const stopAll = () => {
      stopped = true;
      if (poller) clearInterval(poller);
      poller = null;
      if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
      socket = null;
    };

    connect();
    return stopAll;
  }, [reviewId, watching]);

  return { progress, transport };
}
