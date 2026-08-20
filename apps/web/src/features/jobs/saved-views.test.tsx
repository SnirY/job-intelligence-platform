import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SavedViews } from "@/features/jobs/saved-views";

/**
 * Saved views, and the two things that make one worth having.
 *
 * That it says which view is showing and stops saying it the moment a filter
 * moves — a chip still lit over a changed query tells the reader they are
 * somewhere they are not, and does it invisibly, because the list underneath
 * still looks plausible.
 *
 * And that a view this version cannot run is refused rather than run without
 * the part it does not understand.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function view(overrides: Record<string, unknown> = {}) {
  return {
    id: "view-1",
    name: "Remote, strong",
    filters: { work_mode: "REMOTE", min_score: 70 },
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    is_readable: true,
    unreadable: [],
    ...overrides,
  };
}

function server(views: unknown[]) {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({
      url: String(url),
      method,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    if (method === "POST") {
      return { ok: true, status: 201, json: async () => ({ data: view() }) };
    }
    if (method === "DELETE") {
      return { ok: true, status: 204, json: async () => ({ data: null }) };
    }
    return { ok: true, status: 200, json: async () => ({ data: views }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const REMOTE_STRONG = { work_mode: "REMOTE" as const, min_score: 70, page: 1 };

/* Queried by exact name throughout. A chip carries two controls — open, and
   delete — and the delete button's accessible name contains the view's name,
   so a loose regex matches both. */

afterEach(() => vi.unstubAllGlobals());

describe("saved views", () => {
  it("says which view is showing", async () => {
    server([view()]);

    renderWithQuery(<SavedViews query={REMOTE_STRONG} onApply={vi.fn()} />);

    const chip = await screen.findByRole("button", { name: "Remote, strong" });
    expect(chip).toHaveAttribute("aria-current", "true");
  });

  it("stops claiming a view once a filter moves", async () => {
    /* The failure this guards is invisible: the list still looks plausible, so
       a chip left lit is the only thing telling the reader where they are, and
       it would be lying. */
    server([view()]);

    renderWithQuery(<SavedViews query={{ ...REMOTE_STRONG, min_score: 40 }} onApply={vi.fn()} />);

    const chip = await screen.findByRole("button", { name: "Remote, strong" });
    expect(chip).not.toHaveAttribute("aria-current");
  });

  it("ignores the page when deciding which view is showing", async () => {
    // A view is a question. Page three of its answer is still that question.
    server([view()]);

    renderWithQuery(<SavedViews query={{ ...REMOTE_STRONG, page: 3 }} onApply={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Remote, strong" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("applies a view's filters when it is picked", async () => {
    server([view()]);
    const onApply = vi.fn();

    renderWithQuery(<SavedViews query={{ page: 1 }} onApply={onApply} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remote, strong" }));

    expect(onApply).toHaveBeenCalledWith({ work_mode: "REMOTE", min_score: 70 });
  });

  it("saves the question without the page or the empty selects", async () => {
    /* The filter selects express "no filter" as an empty string. Storing that
       would save a view asking for jobs whose work mode is "". */
    const calls = server([]);

    renderWithQuery(
      <SavedViews
        query={{ work_mode: "REMOTE", company: "", min_score: 70, page: 4 }}
        onApply={vi.fn()}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /save this view/i }));
    await userEvent.type(screen.getByLabelText("Name this view"), "Remote, strong");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const posted = calls.find((call) => call.method === "POST");
      expect(posted?.body).toEqual({
        name: "Remote, strong",
        filters: { work_mode: "REMOTE", min_score: 70 },
      });
    });
  });

  it("does not offer to save a view that is already showing", async () => {
    server([view()]);

    renderWithQuery(<SavedViews query={REMOTE_STRONG} onApply={vi.fn()} />);
    await screen.findByRole("button", { name: "Remote, strong" });

    expect(screen.queryByRole("button", { name: /save this view/i })).not.toBeInTheDocument();
  });

  it("stays out of the way on a list nobody has filtered", async () => {
    // The control appears when there is a question on screen worth naming,
    // rather than sitting empty on a first visit asking to be understood.
    server([]);

    const { container } = renderWithQuery(
      <SavedViews query={{ page: 1, sort: "NEWEST", archived: "ACTIVE" }} onApply={vi.fn()} />,
    );

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("says when a name is already taken instead of looking saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? "GET") === "POST") {
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: { message: "You already have a view called 'Remote'." } }),
          };
        }
        return { ok: true, status: 200, json: async () => ({ data: [] }) };
      }),
    );

    renderWithQuery(<SavedViews query={{ work_mode: "REMOTE" }} onApply={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /save this view/i }));
    await userEvent.type(screen.getByLabelText("Name this view"), "Remote");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/already have one with that name/)).toBeInTheDocument();
  });

  it("deletes a view without asking", async () => {
    /* The rule that decides which deletes ask is whether anything goes beyond
       what the row shows. A view holds no data of its own — a name and a
       filter combination, both rebuildable from the screen it was saved from. */
    const calls = server([view()]);

    renderWithQuery(<SavedViews query={REMOTE_STRONG} onApply={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Delete the view/ }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
  });
});

describe("a view this version cannot run", () => {
  it("refuses to open it rather than running it without the filter", async () => {
    /* Running it would return a wider list than the name promises, with
       nothing on screen admitting it — a narrower claim turned into a broader
       one by omission. */
    server([view({ is_readable: false, unreadable: ["seniority"] })]);
    const onApply = vi.fn();

    renderWithQuery(<SavedViews query={{ page: 1 }} onApply={onApply} />);
    await screen.findByText("Remote, strong");

    expect(screen.queryByRole("button", { name: "Remote, strong" })).not.toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("names the filter responsible rather than saying something went wrong", async () => {
    server([view({ is_readable: false, unreadable: ["seniority"] })]);

    renderWithQuery(<SavedViews query={{ page: 1 }} onApply={vi.fn()} />);
    const chip = (await screen.findByText("Remote, strong")).closest("span");

    expect(within(chip as HTMLElement).getByText(/seniority/)).toBeInTheDocument();
  });

  it("can still be deleted", async () => {
    // Otherwise a view nobody can open is also a view nobody can clear away.
    const calls = server([view({ is_readable: false, unreadable: ["seniority"] })]);

    renderWithQuery(<SavedViews query={{ page: 1 }} onApply={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Delete the view/ }));

    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
  });
});
