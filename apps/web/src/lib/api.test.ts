// @vitest-environment node
//
// No DOM here. `vitest.config.mts` sets jsdom for every file, which is right
// for the component tests and pure cost for this one — DEV-058 measured jsdom
// setup as the dominant shared expense in a parallel run. Overriding it per
// file is the supported way to opt out.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, ApiTransportError, apiFetch } from "@/lib/api";

function mockFetch(response: Partial<Response> & { json: () => Promise<unknown> }) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, ...response }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("unwraps the data envelope", async () => {
    mockFetch({ json: async () => ({ data: { status: "ok" } }) });

    await expect(apiFetch<{ status: string }>("/api/v1/health")).resolves.toEqual({
      status: "ok",
    });
  });

  it("throws a typed ApiError carrying the code and request id", async () => {
    mockFetch({
      ok: false,
      status: 503,
      json: async () => ({
        error: {
          code: "SERVICE_UNAVAILABLE",
          message: "A dependency is unavailable.",
          details: { unavailable: ["redis"] },
          request_id: "req-42",
        },
      }),
    });

    const error = await apiFetch("/api/v1/health/ready").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(503);
    expect(apiError.code).toBe("SERVICE_UNAVAILABLE");
    expect(apiError.requestId).toBe("req-42");
    expect(apiError.message).toBe("A dependency is unavailable.");
  });

  it("reports an unreachable API as a transport error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiFetch("/api/v1/health")).rejects.toBeInstanceOf(ApiTransportError);
  });

  it("does not treat a non-JSON response as an empty result", async () => {
    mockFetch({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("Unexpected token <");
      },
    });

    await expect(apiFetch("/api/v1/health")).rejects.toBeInstanceOf(ApiTransportError);
  });
});
