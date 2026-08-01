import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardScreen } from "@/features/dashboard/dashboard";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function dashboard(overrides: Record<string, unknown> = {}) {
  return {
    state: {
      jobs_saved: 0,
      jobs_analysed: 0,
      jobs_matched: 0,
      applications_live: 0,
      profile_skills: 0,
    },
    pipeline: [],
    opportunities: [],
    actions: [],
    activity: [],
    skill_gaps: [],
    ...overrides,
  };
}

function serving(payload: Record<string, unknown>) {
  return vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ data: payload }) }));
}

afterEach(() => vi.unstubAllGlobals());

// --- an account with nothing in it --------------------------------------------

describe("a new account", () => {
  it("reads as unstarted rather than broken", async () => {
    /* An empty dashboard is the state a real new user is in. Rendering it as a
       grid of zeros would be indistinguishable from a dashboard that failed to
       load its numbers. */
    vi.stubGlobal("fetch", serving(dashboard()));

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText(/Nothing here yet/)).toBeInTheDocument();
    expect(screen.queryByText("Jobs saved")).not.toBeInTheDocument();
  });

  it("does not promise more first steps than it offers", async () => {
    /* Found walking 2.10.8 on a second account. The copy read "the two steps
       below" and exactly one action was rendered: a new profile has no saved
       job, so every rule but BUILD_PROFILE has nothing to fire against.

       Asserted as the absence of a count rather than the presence of a
       particular sentence, because the defect was a number written into copy
       that could not see the data it described. */
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          actions: [
            {
              kind: "BUILD_PROFILE",
              subject: "Your career profile",
              reason: "There are no skills on your profile yet.",
              job_id: null,
              application_id: null,
            },
          ],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    const intro = await screen.findByText(/Nothing here yet/);
    expect(intro.textContent).not.toMatch(/\b(one|two|three|\d+)\b/i);
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("surfaces a load failure without claiming data is gone", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText(/Could not load your dashboard/)).toBeInTheDocument();
    expect(screen.getByText(/data is unaffected/)).toBeInTheDocument();
  });
});

// --- what to do next ----------------------------------------------------------

describe("next actions", () => {
  it("shows the evidence behind every suggestion", async () => {
    /* docs/07 requires an observation behind each insight. A recommendation
       with no reason is one the user has to take on trust, which is the thing
       this product is built not to be. */
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          actions: [
            {
              kind: "ANALYSE_JOB",
              subject: "Senior Backend Engineer",
              reason: "Saved, and not yet read into requirements.",
              job_id: "job-1",
              application_id: null,
            },
          ],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(
      await screen.findByText("Saved, and not yet read into requirements."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Read this posting/)).toBeInTheDocument();
  });

  it("points each action at the screen that resolves it", async () => {
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          actions: [
            {
              kind: "MATCH_JOB",
              subject: "Platform Engineer",
              reason: "Read, and never compared against your profile.",
              job_id: "job-9",
              application_id: null,
            },
          ],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    const link = await screen.findByRole("link", { name: /Compare it to your profile/ });
    expect(link).toHaveAttribute("href", "/jobs/job-9");
  });

  it("says so plainly when nothing is waiting", async () => {
    /* The good outcome needs its own words. An empty section here would read
       as a section that failed to render. */
    vi.stubGlobal(
      "fetch",
      serving(dashboard({ state: { ...dashboard().state, jobs_saved: 3, profile_skills: 9 } })),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText(/Nothing is waiting on you/)).toBeInTheDocument();
  });
});

// --- opportunities ------------------------------------------------------------

describe("opportunities", () => {
  const opportunity = {
    job_id: "job-1",
    title: "Senior Backend Engineer",
    company: "Verdant",
    score: 78,
    alignment_label: "Strong alignment",
    is_stale: false,
    has_application: false,
  };

  it("never presents the score as a chance of being hired", async () => {
    // docs/05-ai-and-matching.md is categorical about this wording.
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          opportunities: [opportunity],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(
      await screen.findByText(/Not a prediction about interviews or offers/),
    ).toBeInTheDocument();
    expect(screen.getByText("78%")).toBeInTheDocument();
  });

  it("shows a dash rather than a zero when nothing could be scored", async () => {
    // Zero is a claim about the candidate; a dash is a claim about our data.
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          opportunities: [
            { ...opportunity, score: null, alignment_label: "Not enough profile data" },
          ],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("marks a match whose inputs have changed", async () => {
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          opportunities: [{ ...opportunity, is_stale: true }],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText("Out of date")).toBeInTheDocument();
  });
});

// --- pipeline and gaps --------------------------------------------------------

describe("pipeline", () => {
  it("separates preparation from what has been sent", async () => {
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 2 },
          pipeline: [
            { status: "PREPARING", count: 2, before_applying: true },
            { status: "APPLIED", count: 1, before_applying: false },
          ],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText("Preparing")).toBeInTheDocument();
    expect(screen.getByText("Applied")).toBeInTheDocument();
    expect(screen.getByText("preparing")).toBeInTheDocument();
  });
});

describe("skill gaps", () => {
  it("says what the count is over, so it is not read as market data", async () => {
    /* Counted across the user's own saved jobs. Presented without that, a
       number like "4 jobs" invites being read as a claim about demand. */
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 4 },
          skill_gaps: [{ skill_id: "s-1", name: "Kubernetes", asked_by_jobs: 4 }],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText("Kubernetes")).toBeInTheDocument();
    expect(screen.getByText("4 jobs")).toBeInTheDocument();
    expect(screen.getByText(/Counted across the jobs you saved/)).toBeInTheDocument();
  });

  it("says one job in the singular", async () => {
    vi.stubGlobal(
      "fetch",
      serving(
        dashboard({
          state: { ...dashboard().state, jobs_saved: 1 },
          skill_gaps: [{ skill_id: "s-1", name: "Rust", asked_by_jobs: 1 }],
        }),
      ),
    );

    renderWithQuery(<DashboardScreen greeting="Welcome back" />);

    expect(await screen.findByText("1 job")).toBeInTheDocument();
  });
});
