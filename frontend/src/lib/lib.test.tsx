import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useResource } from "@/hooks/use-resource";
import { ApiError, api, query } from "@/lib/api";
import { formatDuration, formatInr } from "@/lib/format";
import { clearTokens, setSelectedOrganizationId, storeTokens } from "@/lib/tokens";
import { cn } from "@/lib/utils";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(body: unknown = [], status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function headersOf(fetchMock: ReturnType<typeof stubFetch>) {
  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  return init.headers as Record<string, string>;
}

describe("api client", () => {
  it("sends the selected organisation with the bearer token", async () => {
    const fetchMock = stubFetch();
    storeTokens("access-token", "refresh-token");
    setSelectedOrganizationId(20);

    await api.repositories();

    expect(headersOf(fetchMock)).toMatchObject({
      Authorization: "Bearer access-token",
      "X-Organization-Id": "20",
    });
  });

  it("sends no organisation header when none is chosen", async () => {
    const fetchMock = stubFetch();
    storeTokens("access-token", "refresh-token");

    await api.repositories();

    expect(headersOf(fetchMock)).not.toHaveProperty("X-Organization-Id");
  });

  it("signing out forgets the chosen organisation", () => {
    setSelectedOrganizationId(20);
    clearTokens();
    expect(window.localStorage.getItem("codesage.organization")).toBeNull();
  });

  it("surfaces DRF's detail message and the status", async () => {
    stubFetch({ detail: "The audit log requires the owner or admin role." }, 403);
    storeTokens("a", "r");

    const error = await api.auditLog().catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
    expect((error as ApiError).message).toContain("owner or admin");
  });

  it("builds query strings without empty values", () => {
    expect(query({ repository: "", page: 2, status: undefined })).toBe("?page=2");
    expect(query({})).toBe("");
  });
});

describe("useResource", () => {
  it("loads, then reloads on demand", async () => {
    const load = vi.fn().mockResolvedValueOnce("first").mockResolvedValueOnce("second");
    const { result } = renderHook(() => useResource(load, "k"));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe("first"));

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe("second"));
    expect(result.current.loading).toBe(false);
  });

  it("reports the HTTP status of a failure", async () => {
    const { result } = renderHook(() =>
      useResource(() => Promise.reject(new ApiError(404, "Not found.")), "k"),
    );

    await waitFor(() => expect(result.current.status).toBe(404));
    expect(result.current.error).toBe("Not found.");
  });

  it("refetches when the key changes and ignores a stale answer", async () => {
    let resolveSlow: (value: string) => void = () => undefined;
    const slow = new Promise<string>((resolve) => {
      resolveSlow = resolve;
    });
    const { result, rerender } = renderHook(
      ({ key, value }) => useResource(() => (key === "a" ? slow : Promise.resolve(value)), key),
      { initialProps: { key: "a", value: "a" } },
    );

    rerender({ key: "b", value: "b" });
    await waitFor(() => expect(result.current.data).toBe("b"));
    resolveSlow("stale");
    await Promise.resolve();

    expect(result.current.data).toBe("b");
  });
});

describe("format", () => {
  it("durations", () => {
    expect(formatDuration(450)).toBe("450 ms");
    expect(formatDuration(4623)).toBe("4.6 s");
    expect(formatDuration(38000)).toBe("38 s");
    expect(formatDuration(null)).toBe("-");
  });

  it("costs", () => {
    expect(formatInr("0.0648")).toBe("₹0.06");
    expect(formatInr("0.0648", 4)).toBe("₹0.0648");
    expect(formatInr(null)).toBe("-");
  });
});

describe("cn", () => {
  it("keeps a custom font size next to a text colour", () => {
    expect(cn("text-control text-primary-foreground", "text-fg")).toBe("text-control text-fg");
    expect(cn("text-sm", "text-h2")).toBe("text-h2");
    expect(cn("shadow-md", "shadow-popover")).toBe("shadow-popover");
  });
});
