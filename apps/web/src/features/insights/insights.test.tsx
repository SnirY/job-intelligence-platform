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

/** Demand and gaps are separate routes, so the mock has to tell them apart. */
function serving(demand: Record<string, unknown>, gaps: Record<string, unknown>) {
  return vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => ({ data: String(url).includes("/gaps") ? gaps : demand }),
  }));
}

function report(overrides: Record<string, unknown> = {}) {
  return {
    analysed_jobs: 6,
    minimum_jobs: 5,
    above_threshold: true,
    skills: [entry()],
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
