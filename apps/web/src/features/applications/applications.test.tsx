import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApplicationTracker } from "@/features/applications/application-tracker";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function application(overrides: Record<string, unknown> = {}) {
  return {
    id: "app-1",
    job_id: "job-1",
    status: "APPLIED",
    resume_version_id: null,
    applied_at: "2026-07-01T00:00:00Z",
    source: "LINKEDIN",
    notes: null,
    rejection_feedback: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    job_title: "Senior Backend Engineer",
    company: "Verdant",
    allowed_transitions: ["HR_SCREEN", "TECHNICAL_INTERVIEW", "REJECTED"],
    days_in_stage: 3,
    ...overrides,
  };
}

function event(overrides: Record<string, unknown> = {}) {
  return {
    id: "event-1",
    event_type: "STATUS_CHANGED",
    from_status: "PREPARING",
    to_status: "APPLIED",
    occurred_at: "2026-07-01T00:00:00Z",
    summary: "Moved from preparing to applied",
    detail: null,
    ...overrides,
  };
}

/** Dispatches on the URL: the tracker reads the list and, on open, the events. */
function routes(rows: unknown[], events: unknown[] = [event()]) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    const data = String(url).includes("/events") ? events : rows;
    return { ok: true, status: 200, json: async () => ({ data }) };
  });
}

afterEach(() => vi.unstubAllGlobals());

// --- states ---------------------------------------------------------------------

describe("tracker states", () => {
  it("shows a loading state", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderWithQuery(<ApplicationTracker />);

    expect(screen.getByText(/Loading your applications/)).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText(/Could not load your applications/)).toBeInTheDocument();
  });

  it("explains that a job is not automatically an application", async () => {
    // The distinction the phase rests on, said where a user would otherwise
    // wonder why their jobs are not here.
    vi.stubGlobal("fetch", routes([]));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText(/Nothing tracked yet/)).toBeInTheDocument();
    expect(screen.getByText(/only considering does not need an application/)).toBeInTheDocument();
  });
});

// --- the board -------------------------------------------------------------------

describe("the board", () => {
  it("draws a card with its role and company", async () => {
    vi.stubGlobal("fetch", routes([application()]));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText("Senior Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText("Verdant")).toBeInTheDocument();
  });

  it("has no column for an ending", async () => {
    // A Kanban with a Rejected column is a monument to rejection. Ended
    // applications live in the table.
    vi.stubGlobal("fetch", routes([application()]));

    renderWithQuery(<ApplicationTracker />);
    await screen.findByText("Senior Backend Engineer");

    expect(screen.queryByRole("heading", { name: "Rejected" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Withdrawn" })).not.toBeInTheDocument();
  });

  it("accounts for finished applications rather than hiding them silently", async () => {
    vi.stubGlobal("fetch", routes([application({ status: "REJECTED" })]));

    renderWithQuery(<ApplicationTracker />);

    expect(
      await screen.findByText(/1 finished application is not on the board/),
    ).toBeInTheDocument();
  });

  it("shows how long a card has sat where it is", async () => {
    vi.stubGlobal("fetch", routes([application({ days_in_stage: 3 })]));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText("3 days here")).toBeInTheDocument();
  });

  it("suggests a follow-up only once a delay is genuinely unusual", async () => {
    // docs/08 asks for *subtle* stage aging. A card going red after a week
    // would make an ordinary hiring process look like a series of emergencies.
    vi.stubGlobal("fetch", routes([application({ days_in_stage: 30 })]));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText(/worth a follow-up/)).toBeInTheDocument();
  });

  it("says nothing about aging on a card that has not moved yet", async () => {
    vi.stubGlobal("fetch", routes([application({ days_in_stage: null })]));

    renderWithQuery(<ApplicationTracker />);
    await screen.findByText("Senior Backend Engineer");

    expect(screen.queryByText(/days here/)).not.toBeInTheDocument();
  });
});

// --- moving ------------------------------------------------------------------------

describe("moving a card", () => {
  it("offers only the moves the server allows", async () => {
    // The lifecycle table lives in the domain layer. A second copy here would
    // be two rules that have to agree, and the one that drifts is the one the
    // user sees.
    vi.stubGlobal("fetch", routes([application()]));

    renderWithQuery(<ApplicationTracker />);
    const moves = await screen.findByRole("group", { name: /move senior backend engineer/i });

    expect(within(moves).getByRole("button", { name: "HR screen" })).toBeInTheDocument();
    expect(within(moves).getByRole("button", { name: "Technical interview" })).toBeInTheDocument();
    expect(within(moves).queryByRole("button", { name: "Preparing" })).not.toBeInTheDocument();
  });

  it("moves nothing while a keyboard is passing through", async () => {
    /* DEV-074's second copy. This control was a native select mutating on
       `change`, and a native select fires `change` per option under arrow
       keys — so a reader walking the list of moves posted every one of them.
       Status is append-only and each move writes an event, which makes that a
       history of things that never happened rather than a wasted request. */
    const fetchMock = routes([application()]);
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ApplicationTracker />);
    const moves = await screen.findByRole("group", { name: /move senior backend engineer/i });

    within(moves).getByRole("button", { name: "HR screen" }).focus();
    await userEvent.keyboard("{Tab}{Tab}");

    expect(
      fetchMock.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      ),
    ).toHaveLength(0);
  });

  it("PATCHes the chosen status", async () => {
    const fetchMock = routes([application()]);
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ApplicationTracker />);
    const moves = await screen.findByRole("group", { name: /move senior backend engineer/i });
    await userEvent.click(within(moves).getByRole("button", { name: "HR screen" }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(String(patch?.[0])).toContain("/app-1/status");
      expect(JSON.parse(String((patch?.[1] as RequestInit).body))).toEqual({
        status: "HR_SCREEN",
      });
    });
  });

  it("offers nothing on an application that can go no further", async () => {
    vi.stubGlobal("fetch", routes([application({ status: "ARCHIVED", allowed_transitions: [] })]));

    renderWithQuery(<ApplicationTracker />);

    expect(await screen.findByText(/1 finished application/)).toBeInTheDocument();
  });
});

// --- the table ---------------------------------------------------------------------

describe("the table", () => {
  it("shows finished applications the board leaves out", async () => {
    vi.stubGlobal("fetch", routes([application({ status: "REJECTED" })]));

    renderWithQuery(<ApplicationTracker />);
    await userEvent.click(await screen.findByRole("button", { name: /table/i }));

    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Verdant")).toBeInTheDocument();
  });
});

// --- the timeline --------------------------------------------------------------------

describe("the detail view", () => {
  it("shows the timeline when a card is opened", async () => {
    vi.stubGlobal("fetch", routes([application()]));

    renderWithQuery(<ApplicationTracker />);
    await userEvent.click(await screen.findByRole("button", { name: /senior backend engineer/i }));

    expect(await screen.findByText("Moved from preparing to applied")).toBeInTheDocument();
  });

  it("keeps employer feedback apart from anything we concluded", async () => {
    // docs/07: known feedback is stored separately from system inference, and
    // a guessed reason is never presented as fact.
    vi.stubGlobal(
      "fetch",
      routes([application({ rejection_feedback: "Wanted more Kubernetes." })]),
    );

    renderWithQuery(<ApplicationTracker />);
    await userEvent.click(await screen.findByRole("button", { name: /senior backend engineer/i }));

    expect(await screen.findByText("What they told you")).toBeInTheDocument();
    expect(screen.getByText("Wanted more Kubernetes.")).toBeInTheDocument();
    expect(screen.getByText(/never guess a reason/)).toBeInTheDocument();
  });

  it("posts a note to the timeline", async () => {
    const fetchMock = routes([application()]);
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ApplicationTracker />);
    await userEvent.click(await screen.findByRole("button", { name: /senior backend engineer/i }));
    await userEvent.type(await screen.findByLabelText("Note"), "Recruiter replied.");
    await userEvent.click(screen.getByRole("button", { name: /add to timeline/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/app-1/notes"))).toBe(true);
    });
  });
});

// --- what the tracker does not do -------------------------------------------------------

describe("what this phase does not show", () => {
  it("shows no funnel, rates, or conversion metrics", async () => {
    // docs/07 puts the analytics in Phases 9 and 10, and its data-thresholds
    // rule exists because a funnel over four applications is noise.
    vi.stubGlobal("fetch", routes([application()]));

    renderWithQuery(<ApplicationTracker />);
    await screen.findByText("Senior Backend Engineer");

    for (const absent of [/response rate/i, /conversion/i, /funnel/i, /interview rate/i]) {
      expect(screen.queryByText(absent)).not.toBeInTheDocument();
    }
  });
});
