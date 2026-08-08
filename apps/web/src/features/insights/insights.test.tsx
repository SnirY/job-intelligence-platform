import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InsightsScreen } from "@/features/insights/insights";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function entry(overrides: Record<string, unknown> = {}) {
  return {
    key: "python",
    skill_id: "s-1",
    name: "Python",
    catalogued: true,
    jobs: 4,
    share: 67,
    importance: { CORE: 2, PREFERRED: 2 },
    role_families: { BACKEND: 4 },
    state: "STRONG_GAP",
    held: false,
    ...overrides,
  };
}

const EMPTY_ROLES = { minimum_jobs: 3, roles: [] };
const EMPTY_FUNNEL = {
  applications: 0,
  minimum_applications: 5,
  rates_are_meaningful: false,
  stages: [],
};
const EMPTY_RESUMES = { minimum_applications: 5, rates_are_meaningful: false, versions: [] };

/** Five separate routes, so the mock has to tell them apart by URL. */
function serving(
  demand: Record<string, unknown>,
  gaps: Record<string, unknown>,
  extra: Record<string, unknown> = {},
) {
  return vi.fn(async (url: string) => {
    const path = String(url);
    const body = path.includes("/gaps")
      ? gaps
      : path.includes("/roles")
        ? (extra.roles ?? EMPTY_ROLES)
        : path.includes("/funnel")
          ? (extra.funnel ?? EMPTY_FUNNEL)
          : path.includes("/resumes")
            ? (extra.resumes ?? EMPTY_RESUMES)
            : demand;
    return { ok: true, status: 200, json: async () => ({ data: body }) };
  });
}

function report(overrides: Record<string, unknown> = {}) {
  const skills = [entry()];
  return {
    analysed_jobs: 6,
    minimum_jobs: 5,
    above_threshold: true,
    skills,
    // Complete by default. A test that wants a truncated list says so, because
    // the whole question DEV-040 raised is whether the screen admits to hiding
    // rows — and a fixture that quietly hid some would make that untestable.
    total_skills: skills.length,
    shown_skills: 12,
    ...overrides,
  };
}

function gapReport(overrides: Record<string, unknown> = {}) {
  return {
    analysed_jobs: 6,
    minimum_jobs: 5,
    above_threshold: true,
    gaps: [entry()],
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

// --- the wording rules docs/07 imposes ----------------------------------------

describe("what this page is allowed to claim", () => {
  it("describes the user's observed job market, never the market", async () => {
    /* docs/07 is explicit: without broad external data, insights refer to
       "your observed job market". A page implying otherwise would describe an
       industry from a reading list of six postings. */
    vi.stubGlobal("fetch", serving(report(), gapReport()));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/your observed job market/i)).toBeInTheDocument();
  });

  it("says what the counts are over", async () => {
    vi.stubGlobal("fetch", serving(report(), gapReport()));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/6 postings you have saved/i)).toBeInTheDocument();
    // Once in the gap list and once in the demand list: gaps are a subset of
    // what was asked for, so a skill legitimately appears in both.
    expect(screen.getAllByText("4 of 6")).toHaveLength(2);
  });

  it("does not present demand as advice", async () => {
    // docs/07: associations, not causal claims.
    vi.stubGlobal("fetch", serving(report(), gapReport()));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/Not advice about what to learn/i)).toBeInTheDocument();
  });
});

// --- thresholds ---------------------------------------------------------------

describe("minimum data", () => {
  it("withdraws the conclusion without hiding the figures", async () => {
    /* docs/07 asks for explicit minimum-data thresholds, not for silence. A
       user with two saved jobs may see what those two asked for. */
    vi.stubGlobal(
      "fetch",
      serving(
        report({
          analysed_jobs: 2,
          above_threshold: false,
          skills: [entry({ jobs: 2, share: 100 })],
        }),
        gapReport({ analysed_jobs: 2, above_threshold: false, gaps: [] }),
      ),
    );

    renderWithQuery(<InsightsScreen />);

    expect(
      await screen.findByText(/not enough here to call anything a pattern/i),
    ).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
  });

  it("says nothing about thresholds once there is enough", async () => {
    vi.stubGlobal("fetch", serving(report(), gapReport()));

    renderWithQuery(<InsightsScreen />);
    await screen.findAllByText("Python");

    expect(screen.queryByText(/call anything a pattern/i)).not.toBeInTheDocument();
  });
});

// --- gaps ---------------------------------------------------------------------

describe("gaps", () => {
  it("explains what kind of gap each one is", async () => {
    vi.stubGlobal("fetch", serving(report(), gapReport()));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("Not on your profile")).toBeInTheDocument();
    expect(screen.getByText(/Nothing in your profile mentions it/i)).toBeInTheDocument();
  });

  it("distinguishes a listed skill from a demonstrated one", async () => {
    /* The distinction the four states exist for: on the profile is not the
       same as evidenced. */
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [entry({ state: "WEAK_EVIDENCE", held: true })] })),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("Listed, not demonstrated")).toBeInTheDocument();
    expect(screen.getByText(/not attached to any role or project/i)).toBeInTheDocument();
  });

  it("says so plainly when nothing is missing", async () => {
    vi.stubGlobal("fetch", serving(report(), gapReport({ gaps: [] })));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/Nothing is missing/i)).toBeInTheDocument();
  });
});

// --- the catalogue limit ------------------------------------------------------

describe("skills the catalogue does not know", () => {
  it("marks them rather than hiding them", async () => {
    /* The seeded catalogue holds thirty skills and postings name many more.
       Counting only what resolves would report a C++ role as asking for Linux
       and nothing else — so uncatalogued skills are counted, and labelled. */
    vi.stubGlobal(
      "fetch",
      serving(
        report({ skills: [entry({ name: "C++", catalogued: false, skill_id: null, key: "c++" })] }),
        gapReport({ gaps: [] }),
      ),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("C++")).toBeInTheDocument();
    expect(screen.getByText(/as written in the posting/i)).toBeInTheDocument();
  });
});

// --- the demand list is capped, and says so (DEV-040) -------------------------

describe("a list that is short on purpose", () => {
  it("says how many it is not showing", async () => {
    /* DEV-040: the demand list is capped and the gap list is not. A cap the
       screen does not mention is indistinguishable from an answer, which is
       how three real gaps stayed invisible behind a list of twelve. */
    vi.stubGlobal(
      "fetch",
      serving(report({ total_skills: 16, shown_skills: 12 }), gapReport({ gaps: [] })),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/of 16/i)).toBeInTheDocument();
    expect(screen.getByText(/every gap is listed above regardless/i)).toBeInTheDocument();
  });

  it("stays quiet when the list is complete", async () => {
    /* The notice must not appear on an account small enough to show
       everything, or it becomes noise that people learn to skip. */
    vi.stubGlobal("fetch", serving(report(), gapReport({ gaps: [] })));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/What comes up most/i)).toBeInTheDocument();
    expect(screen.queryByText(/Showing the/i)).not.toBeInTheDocument();
  });
});

// --- empty and failed ---------------------------------------------------------

describe("nothing to read yet", () => {
  it("reads as unstarted rather than broken", async () => {
    vi.stubGlobal(
      "fetch",
      serving(
        report({ analysed_jobs: 0, above_threshold: false, skills: [] }),
        gapReport({ analysed_jobs: 0, above_threshold: false, gaps: [] }),
      ),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/Nothing to read yet/i)).toBeInTheDocument();
  });

  it("surfaces a load failure without claiming data is gone", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/Could not load your insights/i)).toBeInTheDocument();
    expect(screen.getByText(/data is unaffected/i)).toBeInTheDocument();
  });
});

// --- role analysis, the funnel, and resumes -----------------------------------

describe("role analysis", () => {
  it("shows a dash rather than an average it cannot support", async () => {
    /* One job in a family is one job wearing a percentage sign. Zero would be
       a verdict on fit; a dash is a statement about how much data there is. */
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        roles: {
          minimum_jobs: 3,
          roles: [
            {
              role_family: "BACKEND",
              jobs: 1,
              matched: 1,
              average_alignment: null,
              applications: 0,
            },
          ],
        },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("Backend engineering")).toBeInTheDocument();
    expect(screen.getByText("too few to average")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("shows the average once there is enough behind it", async () => {
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        roles: {
          minimum_jobs: 3,
          roles: [
            {
              role_family: "BACKEND",
              jobs: 4,
              matched: 4,
              average_alignment: 62,
              applications: 2,
            },
          ],
        },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(screen.getByText("average alignment")).toBeInTheDocument();
  });
});

describe("the funnel", () => {
  /* Chosen so the derived rates cannot collide with the demand fixture's own
     percentage — 1 of 4 is 25%, and nothing else on the page says 25%. */
  const stages = [
    { key: "applied", label: "Applied", reached: 4 },
    { key: "responded", label: "Got a response", reached: 2 },
    { key: "interviewed", label: "Interviewed", reached: 1 },
    { key: "offered", label: "Offer", reached: 0 },
  ];

  it("shows counts and withholds rates below the threshold", async () => {
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        funnel: {
          applications: 3,
          minimum_applications: 5,
          rates_are_meaningful: false,
          stages,
        },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("Applied")).toBeInTheDocument();
    expect(screen.getByText(/Rates need 5 applications/i)).toBeInTheDocument();
    expect(screen.queryByText("25%")).not.toBeInTheDocument();
  });

  it("divides once there is enough to divide by", async () => {
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        funnel: {
          applications: 6,
          minimum_applications: 5,
          rates_are_meaningful: true,
          stages,
        },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("25%")).toBeInTheDocument();
    expect(screen.queryByText(/Rates need/i)).not.toBeInTheDocument();
  });

  it("says the counts come from history, not current status", async () => {
    /* An application rejected after an interview still counts at every stage
       it passed through. The copy has to say so, because a funnel that read
       current statuses would look identical and be wrong. */
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        funnel: { applications: 3, minimum_applications: 5, rates_are_meaningful: false, stages },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText(/ended in a rejection still counts/i)).toBeInTheDocument();
  });
});

describe("resume performance", () => {
  it("does not claim the resume caused the outcome", async () => {
    // docs/07: associations, not causal claims.
    vi.stubGlobal(
      "fetch",
      serving(report(), gapReport({ gaps: [] }), {
        resumes: {
          minimum_applications: 5,
          rates_are_meaningful: false,
          versions: [
            {
              resume_version_id: "rv-1",
              label: "Version 2",
              sent: 3,
              reached_interview: 1,
              offers: 0,
            },
          ],
        },
      }),
    );

    renderWithQuery(<InsightsScreen />);

    expect(await screen.findByText("Version 2")).toBeInTheDocument();
    expect(screen.getByText(/Not a claim that the resume caused it/i)).toBeInTheDocument();
  });
});
