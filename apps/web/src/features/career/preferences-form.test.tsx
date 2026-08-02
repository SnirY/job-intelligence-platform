import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesForm } from "@/features/career/preferences-form";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function preferences(overrides: Record<string, unknown> = {}) {
  return {
    id: "pref-1",
    work_modes: [],
    employment_types: [],
    locations: [],
    open_to_relocation: null,
    salary_min: null,
    salary_currency: null,
    excluded_role_families: [],
    created_at: "2026-08-03T00:00:00Z",
    updated_at: "2026-08-03T00:00:00Z",
    ...overrides,
  };
}

/** Captures the PATCH body so a test can assert what was actually sent. */
function routes(initial: Record<string, unknown>) {
  const sent: Record<string, unknown>[] = [];
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      sent.push(body);
      return {
        ok: true,
        status: 200,
        json: async () => ({ data: { ...initial, ...body } }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ data: initial }) };
  });
  return { fetchMock, sent };
}

afterEach(() => vi.unstubAllGlobals());

describe("career preferences", () => {
  it("round-trips what is stored", async () => {
    const { fetchMock } = routes(
      preferences({ work_modes: ["REMOTE"], locations: ["Tel Aviv", "Haifa"] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<PreferencesForm />);

    expect(await screen.findByRole("button", { name: /remote/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText(/locations/i)).toHaveValue("Tel Aviv\nHaifa");
  });

  it("sends only what changed", async () => {
    // The endpoint is a PATCH. Posting the whole object back would let a form
    // loaded before another tab saved silently reinstate an old restriction.
    const { fetchMock, sent } = routes(preferences({ locations: ["Tel Aviv"] }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithQuery(<PreferencesForm />);
    await user.click(await screen.findByRole("button", { name: /^✓? ?remote$/i }));
    await user.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ work_modes: ["REMOTE"] });
  });

  it("clears a preference with an empty list rather than by omitting it", async () => {
    // Empty means "no constraint". If clearing were expressed by omission the
    // PATCH would leave the old value in place, and the user would believe they
    // had removed a restriction that was still being applied.
    const { fetchMock, sent } = routes(preferences({ work_modes: ["REMOTE"] }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithQuery(<PreferencesForm />);
    await user.click(await screen.findByRole("button", { name: /remote/i }));
    await user.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ work_modes: [] });
  });

  it("cannot be saved when nothing has changed", async () => {
    vi.stubGlobal("fetch", routes(preferences()).fetchMock);
    renderWithQuery(<PreferencesForm />);

    expect(await screen.findByRole("button", { name: /save preferences/i })).toBeDisabled();
  });

  it("leaves relocation unanswered rather than defaulting it to no", async () => {
    // `null` must not narrow anything. A default of "not relocating" would
    // invent a restriction the user never stated.
    vi.stubGlobal("fetch", routes(preferences()).fetchMock);
    renderWithQuery(<PreferencesForm />);

    expect(await screen.findByRole("button", { name: /open to relocating/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: /not relocating/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("says plainly that salary is not compared", async () => {
    // The one dimension we decline to check. Leaving that to silence is how a
    // stored-and-ignored preference happens, which is DEV-035 exactly.
    vi.stubGlobal("fetch", routes(preferences()).fetchMock);
    renderWithQuery(<PreferencesForm />);

    expect(await screen.findByText(/not compared against postings/i)).toBeInTheDocument();
  });

  it("keeps an empty salary empty rather than recording a zero", async () => {
    vi.stubGlobal("fetch", routes(preferences()).fetchMock);
    renderWithQuery(<PreferencesForm />);

    expect(await screen.findByLabelText(/minimum/i)).toHaveValue("");
  });

  it("reports a failed save instead of looking saved", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        return {
          ok: false,
          status: 500,
          json: async () => ({
            error: { code: "INTERNAL_ERROR", message: "Could not save your preferences." },
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({ data: preferences() }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithQuery(<PreferencesForm />);
    await user.click(await screen.findByRole("button", { name: /remote/i }));
    await user.click(screen.getByRole("button", { name: /save preferences/i }));

    expect(await screen.findByText(/could not save/i)).toBeInTheDocument();
  });

  it("does not present the toggles by colour alone", async () => {
    // `docs/08-ui-ux.md` forbids colour as the only signal, and a chip whose
    // state lives in a background shade is exactly that.
    vi.stubGlobal("fetch", routes(preferences({ work_modes: ["HYBRID"] })).fetchMock);
    renderWithQuery(<PreferencesForm />);

    const hybrid = await screen.findByRole("button", { name: /hybrid/i });
    expect(hybrid).toHaveAttribute("aria-pressed", "true");
    expect(hybrid.textContent).toContain("✓");
  });
});
