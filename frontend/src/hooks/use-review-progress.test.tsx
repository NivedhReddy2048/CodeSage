import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({ reviewStatus: vi.fn(), currentUser: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: apiMock,
  ensureFreshToken: () => apiMock.currentUser(),
}));

import { POLL_INTERVAL_MS, useReviewProgress } from "@/hooks/use-review-progress";
import { storeTokens } from "@/lib/tokens";

/** A WebSocket stand-in the test drives by hand. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const snapshot = (completed: number, status = "running", type = "review.snapshot") => ({
  type,
  review_id: 31,
  status,
  agents: {},
  completed,
  total: 5,
});

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  storeTokens("access-token", "refresh-token");
  apiMock.reviewStatus.mockResolvedValue(snapshot(2));
  apiMock.currentUser.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useReviewProgress", () => {
  it("authenticates in the first message, never in the URL", () => {
    renderHook(() => useReviewProgress(31, "running", () => undefined));
    const socket = FakeSocket.instances[0];

    socket.open();

    expect(socket.url).toMatch(/\/ws\/reviews\/31\/$/);
    expect(socket.url).not.toContain("access-token");
    expect(JSON.parse(socket.sent[0])).toEqual({ type: "auth", token: "access-token" });
  });

  it("streams progress, then reports the finish once", () => {
    const onFinished = vi.fn();
    const { result } = renderHook(() => useReviewProgress(31, "running", onFinished));
    const socket = FakeSocket.instances[0];
    socket.open();

    act(() => socket.emit(snapshot(0)));
    act(() => socket.emit({ ...snapshot(3), type: "review.progress", agent: "security", state: "ok" }));
    expect(result.current.progress?.completed).toBe(3);
    expect(result.current.transport).toBe("socket");

    act(() => socket.emit(snapshot(5, "done", "review.finished")));
    act(() => socket.emit(snapshot(5, "done", "review.finished")));

    expect(onFinished).toHaveBeenCalledOnce();
    expect(result.current.transport).toBe("idle");
  });

  it("falls back to polling when the socket drops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useReviewProgress(31, "running", () => undefined));
    act(() => FakeSocket.instances[0].drop(1006));

    await waitFor(() => expect(result.current.transport).toBe("polling"));
    expect(apiMock.reviewStatus).toHaveBeenCalledWith(31);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
    });
    expect(apiMock.reviewStatus.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(result.current.progress?.completed).toBe(2);
  });

  it("polling stops when the review finishes", async () => {
    const onFinished = vi.fn();
    apiMock.reviewStatus.mockResolvedValue(snapshot(5, "done"));
    renderHook(() => useReviewProgress(31, "running", onFinished));

    act(() => FakeSocket.instances[0].drop(1006));

    await waitFor(() => expect(onFinished).toHaveBeenCalledOnce());
  });

  it("an expired token gets one refresh and one reconnect", async () => {
    renderHook(() => useReviewProgress(31, "running", () => undefined));

    act(() => FakeSocket.instances[0].drop(4401));

    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2));
    expect(apiMock.currentUser).toHaveBeenCalledOnce();

    // A second 4401 does not loop: it polls instead.
    act(() => FakeSocket.instances[1].drop(4401));
    await waitFor(() => expect(apiMock.reviewStatus).toHaveBeenCalled());
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("a review that is not visible (4404) stops everything", async () => {
    const { result } = renderHook(() => useReviewProgress(31, "running", () => undefined));

    act(() => FakeSocket.instances[0].drop(4404));

    expect(result.current.transport).toBe("idle");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiMock.reviewStatus).not.toHaveBeenCalled();
  });

  it("a finished review opens no socket at all", () => {
    renderHook(() => useReviewProgress(31, "done", () => undefined));
    expect(FakeSocket.instances).toHaveLength(0);
  });
});
