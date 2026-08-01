import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobMatchPanel } from "@/features/jobs/job-match";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    title: "Senior Backend Engineer",
    company: "Verdant",
    location: "Lisbon",
    work_mode: "HYBRID",
    employment_type: "FULL_TIME",
    seniority: null,
    role_family: null,
    description: "We are hiring.",
    source_url: null,
    import_method: "PASTED_DESCRIPTION",
    status: "ANALYZED",
    notes: null,
    salary_text: null,
    fetch_error: null,
    archived_at: null,
    created_at: "2026-07-27T00:00:00Z",
    updated_at: "2026-07-27T00:00:00Z",
    ...overrides,
  } as never;
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    requirement_id: "req-1",
    status: "STRONG_MATCH",
    category: "TECHNICAL",
    score: 100,
    weight: 3,
    confidence: 90,
    explanation: "You have Python and have used it in at least one role.",
    is_blocker: false,
    source_order: 0,
    evidence: [
      {
        id: "ev-1",
        evidence_type: "SKILL",
        entity_id: "skill-1",
        label: "Python",
        detail: "Expert, 6 years",
        verification_status: "USER_CONFIRMED",
        relevance: 80,
      },
    ],
    ...overrides,
  };
}

function match(overrides: Record<string, unknown> = {}) {
  return {
    id: "match-1",
    job_id: "job-1",
    version: 1,
    overall_score: 78,
    alignment_label: "Good alignment",
    score_cap: null,
    score_cap_reason: null,
    recommendation: "APPLY",
    recommendation_reasons: ["Your profile covers the important requirements."],
    confidence: 80,
    summary: null,
    category_scores: {
      TECHNICAL: { category: "TECHNICAL", score: 82, weight: 5, item_count: 2, scored_count: 2 },
    },
    status_counts: { STRONG_MATCH: 1 },
    has_blockers: false,
    scored_requirements: 2,
    total_requirements: 3,
    warnings: [],
    analysis_version: 1,
    engine_version: "1.0.0",
    computed_at: "2026-07-27T00:00:00Z",
    created_at: "2026-07-27T00:00:00Z",
    ...overrides,
  };
}

function view(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "job-1",
    match: match(),
    items: [item()],
    is_stale: false,
    stale_reasons: [],
    available_versions: [1],
    can_match: true,
    blocking_reason: null,
    ...overrides,
  };
}

function routes(payload: Record<string, unknown>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    void url;
    if (init?.method === "POST") {
      return { ok: true, status: 200, json: async () => ({ data: payload }) };
    }
    return { ok: true, status: 200, json: async () => ({ data: payload }) };
  });
}

afterEach(() => vi.unstubAllGlobals());

// --- states -------------------------------------------------------------------

describe("match states", () => {
  it("shows a loading state", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(screen.getByText(/Loading the match/)).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/Could not load the match/)).toBeInTheDocument();
  });

  it("offers to match a job that has never been matched", async () => {
    vi.stubGlobal("fetch", routes(view({ match: null, items: [], available_versions: [] })));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/has not been matched yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /match against my profile/i })).toBeEnabled();
  });

  it("will not offer to match a job with no analysis", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          match: null,
          items: [],
          available_versions: [],
          can_match: false,
          blocking_reason: "This job has not been analysed yet.",
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job({ status: "RAW" })} />);

    expect(await screen.findByRole("button", { name: /match against my profile/i })).toBeDisabled();
    expect(screen.getByText(/has not been analysed yet/)).toBeInTheDocument();
  });

  it("posts when the user asks for a match", async () => {
    const fetchMock = routes(view({ match: null, items: [], available_versions: [] }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText(/has not been matched yet/);

    await userEvent.click(screen.getByRole("button", { name: /match against my profile/i }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.some(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(posted).toBe(true);
    });
  });
});

// --- the score ------------------------------------------------------------------

describe("the score", () => {
  it("shows the alignment score and its label", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("78%")).toBeInTheDocument();
    expect(screen.getByText("Good alignment")).toBeInTheDocument();
  });

  it("never presents the score as a chance of being hired", async () => {
    // docs/05-ai-and-matching.md is categorical about this.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("78%");

    expect(screen.getByText(/Not a prediction about interviews or offers/)).toBeInTheDocument();
    for (const forbidden of [/chance of/i, /likely to get/i, /probability/i, /odds/i]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
    }
  });

  it("shows a dash rather than a zero when nothing could be scored", async () => {
    // Zero is a claim about the candidate; a dash is a claim about our data.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          match: match({
            overall_score: null,
            alignment_label: "Not enough profile data",
            recommendation: "CONSIDER",
          }),
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.getByText("Not enough profile data")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("says how much of the posting was actually checked", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("2 of 3")).toBeInTheDocument();
  });

  it("explains a capped score", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          match: match({
            overall_score: 45,
            score_cap: 45,
            score_cap_reason: "Capped at 45 because 1 essential requirement has no evidence.",
            has_blockers: true,
          }),
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/Capped at 45/)).toBeInTheDocument();
  });

  it("records the engine and analysis versions", async () => {
    // A score without them is not reproducible.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/matching engine 1\.0\.0/)).toBeInTheDocument();
  });
});

// --- recommendation ---------------------------------------------------------------

describe("recommendation", () => {
  it("shows the recommendation and its reasons", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("Apply")).toBeInTheDocument();
    expect(screen.getByText(/covers the important requirements/)).toBeInTheDocument();
  });

  it("keeps the recommendation separate from the number", async () => {
    // A 70% with a blocker is not the same advice as a 70% without one.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          match: match({
            overall_score: 72,
            recommendation: "LOW_PRIORITY",
            has_blockers: true,
            recommendation_reasons: ["1 essential requirement has no evidence in your profile."],
          }),
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("72%")).toBeInTheDocument();
    expect(screen.getByText("Low priority")).toBeInTheDocument();
  });
});

// --- verdicts and evidence ---------------------------------------------------------

describe("requirements and evidence", () => {
  it("lists every requirement with its verdict", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("Requirement by requirement")).toBeInTheDocument();
    expect(screen.getAllByText(/You have Python/).length).toBeGreaterThan(0);
  });

  it("keeps the evidence one click away", async () => {
    // docs/08-ui-ux.md: the user should be able to ask "why does the system
    // think I match this?" and see the exact evidence.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("Requirement by requirement");

    expect(screen.queryByText("Expert, 6 years")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /why\?/i }));

    expect(await screen.findByText("Expert, 6 years")).toBeInTheDocument();
  });

  it("flags evidence the user has not confirmed", async () => {
    // Unverified data may be cited, but it must never look like a confirmed
    // fact.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          items: [
            item({
              status: "PARTIAL_MATCH",
              evidence: [
                {
                  id: "ev-1",
                  evidence_type: "SKILL",
                  entity_id: "skill-1",
                  label: "Docker",
                  detail: null,
                  verification_status: "AI_INFERRED",
                  relevance: 80,
                },
              ],
            }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("Requirement by requirement");

    await userEvent.click(screen.getByRole("button", { name: /why\?/i }));

    expect(await screen.findByText("Not yet confirmed by you")).toBeInTheDocument();
  });

  it("says plainly when there is no evidence for a requirement", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          items: [
            item({ status: "GAP", explanation: "Rust is not in your profile.", evidence: [] }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/No evidence in your profile/)).toBeInTheDocument();
  });

  it("labels every status in words as well as colour", async () => {
    // docs/08-ui-ux.md: never rely on colour alone.
    vi.stubGlobal("fetch", routes(view({ items: [item({ status: "TRANSFERABLE_MATCH" })] })));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("Transferable")).toBeInTheDocument();
  });
});

// --- sections ---------------------------------------------------------------------

describe("sections", () => {
  it("shows blockers in their own section", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          match: match({ has_blockers: true }),
          items: [
            item({
              status: "BLOCKER",
              is_blocker: true,
              explanation: "Rust is not in your profile. This is listed as essential.",
              evidence: [],
            }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("Blockers")).toBeInTheDocument();
  });

  it("separates transferable matches from real ones", async () => {
    // The distinction the transferability design exists to preserve.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          items: [
            item({
              id: "i2",
              status: "TRANSFERABLE_MATCH",
              explanation: "You have FastAPI, not Spring Boot.",
              evidence: [],
            }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("Related, but not the same")).toBeInTheDocument();
  });

  it("shows the category breakdown", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("By category")).toBeInTheDocument();
    expect(screen.getByText("Technical skills")).toBeInTheDocument();
  });

  it("omits sections that have nothing in them", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("Requirement by requirement");

    expect(screen.queryByText("Blockers")).not.toBeInTheDocument();
    expect(screen.queryByText("Gaps")).not.toBeInTheDocument();
  });
});

// --- staleness and history ----------------------------------------------------------

describe("staleness and history", () => {
  it("warns when the match is out of date and says why", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          is_stale: true,
          stale_reasons: ["Your career profile has changed since this match."],
        }),
      ),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText("This match is out of date.")).toBeInTheDocument();
    expect(screen.getByText(/career profile has changed/)).toBeInTheDocument();
  });

  it("does not warn about a fresh match", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("78%");

    expect(screen.queryByText("This match is out of date.")).not.toBeInTheDocument();
  });

  it("offers to recalculate", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByRole("button", { name: /recalculate/i })).toBeInTheDocument();
  });

  it("says so when a recalculation fails", async () => {
    /* Same shape as the analysis panel's silent refusal: the empty state
       reported a failed request, a match already on screen had nowhere to, so
       the click read as ignored. Feedback belongs beside the button. */
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          return { ok: false, status: 500, json: async () => ({ error: { message: "boom" } }) };
        }
        return { ok: true, status: 200, json: async () => ({ data: view() }) };
      }),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);
    await userEvent.click(await screen.findByRole("button", { name: /recalculate/i }));

    expect(await screen.findByText(/could not be recalculated/i)).toBeInTheDocument();
    // The existing match stays put. A failed request changes nothing.
    expect(screen.getByText("78%")).toBeInTheDocument();
  });

  it("offers earlier matches once there is more than one", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ match: match({ version: 2 }), available_versions: [2, 1] })),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
  });

  it("requests an older version when one is picked", async () => {
    const fetchMock = routes(view({ match: match({ version: 2 }), available_versions: [2, 1] }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByRole("button", { name: "v1" });

    await userEvent.click(screen.getByRole("button", { name: "v1" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("version=1"))).toBe(true);
    });
  });

  it("says which version is being read when it is not the latest", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ match: match({ version: 1 }), available_versions: [2, 1] })),
    );

    renderWithQuery(<JobMatchPanel job={job()} />);

    expect(await screen.findByText(/reading version 1 of 2/)).toBeInTheDocument();
  });
});

// --- what must not appear -------------------------------------------------------------

describe("what this phase does not show", () => {
  it("shows no resume tailoring or application data", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobMatchPanel job={job()} />);
    await screen.findByText("78%");

    for (const absent of [
      /resume strategy/i,
      /tailor/i,
      /application status/i,
      /mark as applied/i,
    ]) {
      expect(screen.queryByText(absent)).not.toBeInTheDocument();
    }
  });
});
