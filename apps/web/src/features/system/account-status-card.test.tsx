import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountStatusCard } from "@/features/system/account-status-card";

const getToken = vi.fn<() => Promise<string | null>>();

// The card is exercised through the real API client, so the assertions cover
// token attachment and envelope handling rather than a stubbed hook.
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken }),
}));

function renderCard(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
  getToken.mockReset();
});

describe("AccountStatusCard", () => {
  it("sends the session token as a bearer credential", async () => {
    getToken.mockResolvedValue("session-token-abc");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: {
          id: "6a1f0c2e-0000-4000-8000-000000000000",
          email: "alice@example.com",
          display_name: "Alice",
          created_at: "2026-07-25T00:00:00Z",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderCard(<AccountStatusCard />);

    expect(await screen.findByText("Verified")).toBeInTheDocument();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer session-token-abc");
  });

  it("shows the account once the API confirms the session", async () => {
    getToken.mockResolvedValue("session-token-abc");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            id: "6a1f0c2e-0000-4000-8000-000000000000",
            email: "alice@example.com",
            display_name: "Alice",
            created_at: "2026-07-25T00:00:00Z",
          },
        }),
      }),
    );

    renderCard(<AccountStatusCard />);

    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("distinguishes a rejected session from an unreachable API", async () => {
    getToken.mockResolvedValue("expired-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({
          error: {
            code: "UNAUTHENTICATED",
            message: "Authentication is required.",
            details: null,
            request_id: "req-1",
          },
        }),
      }),
    );

    renderCard(<AccountStatusCard />);

    expect(await screen.findByText("Not authenticated")).toBeInTheDocument();
    expect(screen.getByText(/did not accept this session/)).toBeInTheDocument();
  });

  it("reports an unreachable API without claiming the session is invalid", async () => {
    getToken.mockResolvedValue("session-token-abc");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderCard(<AccountStatusCard />);

    expect(await screen.findByText("Unreachable")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the API.")).toBeInTheDocument();
    // A transport failure must not be reported as a rejected session — they
    // call for completely different user actions.
    expect(screen.queryByText(/did not accept this session/)).not.toBeInTheDocument();
  });

  it("shows a loading state while the session is being verified", () => {
    getToken.mockReturnValue(new Promise(() => {}));
    vi.stubGlobal("fetch", vi.fn());

    renderCard(<AccountStatusCard />);

    expect(screen.getByText(/Verifying your session/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
  });

  it("omits the Authorization header when no session token is available", async () => {
    getToken.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({
        error: {
          code: "UNAUTHENTICATED",
          message: "Authentication is required.",
          details: null,
          request_id: "req-2",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderCard(<AccountStatusCard />);

    await screen.findByText("Not authenticated");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});
