import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TargetRolesSection } from "@/features/career/target-roles-section";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

const role = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Backend Engineer",
  role_family: "Backend",
  desired_seniority: "JUNIOR" as const,
  priority: 1,
  is_active: true,
  notes: null,
  created_at: "2026-07-26T00:00:00Z",
  updated_at: "2026-07-26T00:00:00Z",
};

function listResponse(items: unknown[]) {
  return { ok: true, status: 200, json: async () => ({ data: items }) };
}

function renderSection(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TargetRolesSection", () => {
  it("invites the first entry when there are none", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(listResponse([])));

    renderSection(<TargetRolesSection />);

    expect(await screen.findByText(/No target roles yet/)).toBeInTheDocument();
  });

  it("lists existing roles with their status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(listResponse([role])));

    renderSection(<TargetRolesSection />);

    expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Backend · Junior · Priority 1/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("will not submit a blank title", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(listResponse([])));

    renderSection(<TargetRolesSection />);

    const submit = await screen.findByRole("button", { name: /Add target role/ });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Role title"), "   ");
    expect(submit).toBeDisabled();
  });

  it("posts a trimmed title and refreshes the list", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ data: role }) })
      .mockResolvedValue(listResponse([role]));
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<TargetRolesSection />);

    await userEvent.type(await screen.findByLabelText("Role title"), "  Backend Engineer  ");
    await userEvent.click(screen.getByRole("button", { name: /Add target role/ }));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));

    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/api/v1/career/target-roles");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string).title).toBe("Backend Engineer");
  });

  it("explains a duplicate title rather than failing silently", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: {
            code: "CONFLICT",
            message: "A target role titled 'Backend Engineer' already exists.",
            details: null,
            request_id: "req-1",
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<TargetRolesSection />);

    await userEvent.type(await screen.findByLabelText("Role title"), "Backend Engineer");
    await userEvent.click(screen.getByRole("button", { name: /Add target role/ }));

    expect(
      await screen.findByText("You already have a target role with that title."),
    ).toBeInTheDocument();
  });

  it("treats a 204 delete as success rather than a transport error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(listResponse([role]))
      // 204 carries no body; parsing one would throw and report a successful
      // delete as a failure.
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => {
          throw new SyntaxError("Unexpected end of JSON input");
        },
      })
      .mockResolvedValue(listResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<TargetRolesSection />);

    await userEvent.click(await screen.findByRole("button", { name: "Remove Backend Engineer" }));

    expect(await screen.findByText(/No target roles yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Could not remove/)).not.toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderSection(<TargetRolesSection />);

    expect(await screen.findByText("Could not load your target roles.")).toBeInTheDocument();
  });
});
