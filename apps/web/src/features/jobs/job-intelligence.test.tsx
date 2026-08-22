import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobIntelligence } from "@/features/jobs/job-intelligence";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    title: "Senior Backend Engineer",
    company: "Verdant Logistics",
    location: "Lisbon",
    work_mode: "HYBRID",
    employment_type: "FULL_TIME",
    seniority: null,
    role_family: null,
    description: "We are hiring.",
    source_url: null,
    import_method: "PASTED_DESCRIPTION",
    status: "RAW",
    notes: null,
    salary_text: null,
    fetch_error: null,
    archived_at: null,
    created_at: "2026-07-27T00:00:00Z",
    updated_at: "2026-07-27T00:00:00Z",
    ...overrides,
  } as never;
}

function requirement(overrides: Record<string, unknown> = {}) {
  return {
    id: "req-1",
    requirement_type: "TECHNICAL_SKILL",
    importance: "REQUIRED",
    explicitness: "EXPLICIT",
    source_text: "Strong Python and PostgreSQL",
    normalized_text: "Python",
    confidence: 90,
    source_order: 0,
    skill_id: "skill-1",
    skill_name: "Python",
    years_min: null,
    ...overrides,
  };
}

function analysis(overrides: Record<string, unknown> = {}) {
  return {
    id: "analysis-1",
    job_id: "job-1",
    version: 1,
    summary: "A senior backend role owning delivery routing.",
    role_family: "BACKEND",
    secondary_role_family: null,
    role_family_confidence: 92,
    role_family_reasoning: "Server-side routing services in Python.",
    seniority: "SENIOR",
    seniority_confidence: 88,
    seniority_reasoning: "Asks for 5+ years and expects platform ownership.",
    domain: "logistics",
    years_experience_min: 5,
    years_experience_max: null,
    model: "claude-opus-5",
    parse_prompt_version: "job_parser_v1",
    analysis_prompt_version: "job_analysis_v1",
    warnings: [],
    analyzed_at: "2026-07-27T00:00:00Z",
    created_at: "2026-07-27T00:00:00Z",
    ...overrides,
  };
}

function view(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "job-1",
    job_status: "ANALYZED",
    analysis: analysis(),
    requirements: [requirement()],
    responsibilities: [],
    processing: null,
    is_stale: false,
    available_versions: [1],
    can_analyze: true,
    ...overrides,
  };
}

/** Routes fetches by URL; the panel reads one endpoint and posts to another. */
function routes(payload: Record<string, unknown>, onPost?: () => unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const result = onPost?.();
      return {
        ok: true,
        status: 202,
        json: async () =>
          result ?? {
            data: { job_id: "job-1", processing_job_id: "pj-1", status: "PENDING" },
          },
      };
    }
    void url;
    return { ok: true, status: 200, json: async () => ({ data: payload }) };
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- states -------------------------------------------------------------------

describe("analysis states", () => {
  it("shows a loading state before the analysis arrives", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(screen.getByText(/Loading the analysis/)).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/Could not load the analysis/)).toBeInTheDocument();
  });

  it("offers to analyse a job that has never been read", async () => {
    vi.stubGlobal("fetch", routes(view({ analysis: null, available_versions: [] })));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/has not been analysed yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyse this posting/i })).toBeEnabled();
  });

  it("will not offer to analyse a job with nothing to read", async () => {
    // The button's enabled state and the endpoint's 409 rule have to agree, or
    // the user clicks something that fails.
    vi.stubGlobal(
      "fetch",
      routes(view({ analysis: null, available_versions: [], can_analyze: false })),
    );

    renderWithQuery(<JobIntelligence job={job({ description: null })} />);

    expect(await screen.findByRole("button", { name: /analyse this posting/i })).toBeDisabled();
    expect(screen.getByText(/Add a description first/)).toBeInTheDocument();
  });

  it("says an analysis is in progress", async () => {
    vi.stubGlobal("fetch", routes(view({ analysis: null, job_status: "PARSING" })));

    renderWithQuery(<JobIntelligence job={job({ status: "PARSING" })} />);

    expect(await screen.findByText(/Reading the posting/)).toBeInTheDocument();
  });

  it("distinguishes the two stages of a running analysis", async () => {
    vi.stubGlobal("fetch", routes(view({ analysis: null, job_status: "ANALYZING" })));

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYZING" })} />);

    expect(await screen.findByText(/what kind of role this is/)).toBeInTheDocument();
  });

  it("does not offer the analyse button while one is running", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ analysis: null, job_status: "PARSING", can_analyze: false })),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "PARSING" })} />);
    await screen.findByText(/Reading the posting/);

    expect(screen.queryByRole("button", { name: /analyse this posting/i })).not.toBeInTheDocument();
  });

  it("posts when the user asks for an analysis", async () => {
    const fetchMock = routes(view({ analysis: null, available_versions: [] }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText(/has not been analysed yet/);

    await userEvent.click(screen.getByRole("button", { name: /analyse this posting/i }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.some(([url, init]) => {
        const request = init as RequestInit | undefined;
        return request?.method === "POST" && String(url).endsWith("/analysis");
      });
      expect(posted).toBe(true);
    });
  });

  it("says which of the two steps is running", async () => {
    vi.stubGlobal("fetch", routes(view({ analysis: null, job_status: "ANALYZING" })));

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYZING" })} />);

    expect(await screen.findByText(/Step 2 of 2/)).toBeInTheDocument();
  });

  it("says which attempt this is once the first has failed", async () => {
    /* "Working…" for a minute is indistinguishable from nothing happening.
       When the first attempt failed and a second is running, saying so is the
       difference between waiting and giving up. */
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: null,
          job_status: "PARSING",
          processing: {
            id: "pj-1",
            status: "RUNNING",
            step: "PARSING",
            attempts: 2,
            error_code: null,
            error_message: null,
            is_retriable: true,
          },
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "PARSING" })} />);

    expect(await screen.findByText(/Attempt 2/)).toBeInTheDocument();
  });

  it("reports progress beside the button that started it, not at the top", async () => {
    /* The user's complaint: with a reading already on screen, "Analyse again"
       sits below a requirement list several screens long. Reporting the click
       at the top of the panel reports it nowhere they are looking.

       Asserted as document order against the requirements, which are what sits
       between the two positions — the thing that made the old placement
       useless. */
    vi.stubGlobal("fetch", routes(view({ job_status: "PARSING" })));

    renderWithQuery(<JobIntelligence job={job({ status: "PARSING" })} />);

    const progress = await screen.findByText(/Step 1 of 2/);
    const requirements = screen.getByRole("heading", { name: /^requirements$/i });
    const button = screen.getByRole("button", { name: /analysing/i });

    const follows = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

    expect(follows(requirements, progress)).toBe(true);
    expect(follows(progress, button)).toBe(true);
  });

  it("disables Analyse again while an analysis is already running", async () => {
    vi.stubGlobal("fetch", routes(view({ job_status: "ANALYZING" })));

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYZING" })} />);

    expect(await screen.findByRole("button", { name: /analysing/i })).toBeDisabled();
  });
});

// --- failure ------------------------------------------------------------------

describe("a failed analysis", () => {
  it("explains the failure and offers a retry", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: null,
          job_status: "ANALYSIS_FAILED",
          processing: {
            id: "pj-1",
            status: "FAILED",
            step: "PARSING",
            attempts: 1,
            error_code: "PROVIDER_ERROR",
            error_message: "The model could not be reached.",
            is_retriable: true,
          },
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYSIS_FAILED" })} />);

    expect(await screen.findByText(/could not be reached/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("says the job itself is untouched", async () => {
    // The recovery for this is a retry, not re-entering a description that is
    // already there — unlike a failed URL import, which offers a paste box.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: null,
          job_status: "ANALYSIS_FAILED",
          processing: {
            id: "pj-1",
            status: "FAILED",
            step: "PARSING",
            attempts: 1,
            error_code: "PROVIDER_ERROR",
            error_message: null,
            is_retriable: true,
          },
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYSIS_FAILED" })} />);

    expect(await screen.findByText(/description are untouched/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Job description")).not.toBeInTheDocument();
  });

  it("hides the retry when retrying cannot help", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: null,
          job_status: "ANALYSIS_FAILED",
          processing: {
            id: "pj-1",
            status: "FAILED",
            step: "PARSING",
            attempts: 5,
            error_code: "CONTENT_UNAVAILABLE",
            error_message: "There is nothing to read.",
            is_retriable: false,
          },
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYSIS_FAILED" })} />);
    await screen.findByText(/nothing to read/);

    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("keeps the previous analysis visible after a failed reanalysis", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          job_status: "ANALYSIS_FAILED",
          processing: {
            id: "pj-2",
            status: "FAILED",
            step: "PARSING",
            attempts: 1,
            error_code: "TIMEOUT",
            error_message: "That took too long.",
            is_retriable: true,
          },
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job({ status: "ANALYSIS_FAILED" })} />);

    expect(await screen.findByText(/took too long/)).toBeInTheDocument();
    expect(screen.getByText("Senior")).toBeInTheDocument();
  });

  it("says so when Analyse again is refused", async () => {
    /* Checklist item 2.5.4. A job with no analysis yet reports a refused
       request through its empty state; a job that had already been analysed
       had nowhere to put one, so a 409 — the response to asking while an
       analysis is in flight — produced no change on screen whatsoever. The
       user clicked, read the same page back, and concluded the button was
       broken. */
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: { message: "This job is already being analysed." } }),
          };
        }
        return { ok: true, status: 200, json: async () => ({ data: view() }) };
      }),
    );

    renderWithQuery(<JobIntelligence job={job()} />);
    await userEvent.click(await screen.findByRole("button", { name: /analyse again/i }));

    expect(await screen.findByText(/could not be started/i)).toBeInTheDocument();
    // The reading itself stays put. A refused request changes nothing.
    expect(screen.getByText("Senior")).toBeInTheDocument();
  });
});

// --- the analysis itself ------------------------------------------------------

describe("a completed analysis", () => {
  it("shows the overview", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/owning delivery routing/)).toBeInTheDocument();
    expect(screen.getByText("logistics")).toBeInTheDocument();
    expect(screen.getByText("5+ years")).toBeInTheDocument();
  });

  it("shows the role family and seniority with their reasoning", async () => {
    // A judgement without its grounds is an assertion, and this panel is the
    // one place the user can see what a level was based on.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("Backend engineering")).toBeInTheDocument();
    expect(screen.getByText("Senior")).toBeInTheDocument();
    expect(screen.getByText(/expects platform ownership/)).toBeInTheDocument();
  });

  it("labels the analysis as a reading rather than as the posting", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/not the posting itself/)).toBeInTheDocument();
    expect(screen.getByText(/The posting does not say these directly/)).toBeInTheDocument();
  });

  it("shows an unclear seniority as unclear", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: analysis({
            seniority: "UNKNOWN",
            seniority_reasoning: null,
            seniority_confidence: 0,
          }),
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("Not clear from the posting")).toBeInTheDocument();
  });

  it("names a second role family when there is one", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ analysis: analysis({ secondary_role_family: "DATA_ENGINEERING" }) })),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/Also Data engineering/)).toBeInTheDocument();
  });

  it("describes confidence in words, not only as a number", async () => {
    // "84%" invites the reader to treat a model's self-report as a
    // measurement.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findAllByText(/Clear from the posting/)).not.toHaveLength(0);
  });

  it("records which model and prompts produced the reading", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/job_parser_v1/)).toBeInTheDocument();
    expect(screen.getByText(/job_analysis_v1/)).toBeInTheDocument();
  });
});

// --- requirements -------------------------------------------------------------

describe("requirements", () => {
  it("lists them under their type", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("Technical skills")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
  });

  it("distinguishes required from preferred", async () => {
    // The distinction the whole phase turns on: a preference shown as a demand
    // makes someone skip a job they should apply for.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          requirements: [
            requirement({ id: "r1", normalized_text: "Python", importance: "REQUIRED" }),
            requirement({ id: "r2", normalized_text: "Kubernetes", importance: "PREFERRED" }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("Required")).toBeInTheDocument();
    expect(screen.getByText("Preferred")).toBeInTheDocument();
  });

  it("counts the split in the header", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          requirements: [
            requirement({ id: "r1", importance: "CORE" }),
            requirement({ id: "r2", normalized_text: "K8s", importance: "PREFERRED" }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/1 required, 1 preferred/)).toBeInTheDocument();
  });

  it("shows the posting's own words beside every reading, with no click at all", async () => {
    /* The check that makes the whole panel trustworthy: any reading can be
       compared against what was actually written. It used to be one click —
       the quote sat behind a per-row disclosure, so the resting state of the
       list was our normalisation standing alone.

       `evidence-chain.tsx` states the rule that breaks, about itself: the quote
       and the reading are never rendered without the other. A closed disclosure
       breaks it on every row simultaneously, which is the version nobody
       notices, because nothing on screen looks missing. */
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("Strong Python and PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show the posting's words/i }),
    ).not.toBeInTheDocument();
  });

  it("heads the two columns once rather than per row", async () => {
    // The same vocabulary the evidence chain uses for its first two links, so a
    // reader who has seen one recognises the other.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("What the posting said")).toBeInTheDocument();
    expect(screen.getByText("How we read it")).toBeInTheDocument();
  });

  it("marks an implied requirement as implied", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ requirements: [requirement({ explicitness: "IMPLIED" })] })),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/Implied by the posting/)).toBeInTheDocument();
  });

  it("shows years attached to a requirement", async () => {
    // The overview carries the posting's overall years figure; this is the one
    // attached to a single requirement, so the fixture clears the former to
    // keep the assertion about the latter.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: analysis({ years_experience_min: null }),
          requirements: [
            requirement({
              requirement_type: "EXPERIENCE",
              normalized_text: "Backend engineering",
              years_min: 3,
            }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("3+ years")).toBeInTheDocument();
  });

  it("puts what can rule someone out first", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          requirements: [
            requirement({ id: "r1", requirement_type: "SOFT_SKILL", normalized_text: "Teamwork" }),
            requirement({
              id: "r2",
              requirement_type: "WORK_AUTHORIZATION",
              normalized_text: "Right to work in Portugal",
            }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText("Teamwork");

    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings.indexOf("Work authorisation")).toBeLessThan(
      headings.indexOf("Ways of working"),
    );
  });

  it("says so when nothing reads as a requirement", async () => {
    vi.stubGlobal("fetch", routes(view({ requirements: [] })));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/That is unusual/)).toBeInTheDocument();
  });
});

// --- responsibilities ---------------------------------------------------------

describe("responsibilities", () => {
  it("lists them separately from requirements", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          responsibilities: [
            {
              id: "resp-1",
              text: "Design and build routing services",
              source_text: "You will design and build our routing services",
              confidence: 90,
              source_order: 0,
            },
          ],
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText("What you would do")).toBeInTheDocument();
    expect(screen.getByText("Design and build routing services")).toBeInTheDocument();
  });

  it("omits the section when there are none", async () => {
    vi.stubGlobal("fetch", routes(view({ responsibilities: [] })));

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText("Python");

    expect(screen.queryByText("What you would do")).not.toBeInTheDocument();
  });
});

// --- warnings, staleness, versions --------------------------------------------

describe("reanalysis and history", () => {
  it("tells the user what validation corrected", async () => {
    // A reading that silently dropped four requirements looks the same as one
    // that found four fewer, and the difference decides whether to trust it.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          analysis: analysis({
            warnings: ["2 requirements quoted text that is not in this posting."],
          }),
        }),
      ),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/quoted text that is not in this posting/)).toBeInTheDocument();
  });

  it("warns when the description changed after the analysis", async () => {
    vi.stubGlobal("fetch", routes(view({ is_stale: true })));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/has been edited since this was read/)).toBeInTheDocument();
  });

  it("does not warn about staleness on a fresh analysis", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText("Python");

    expect(screen.queryByText(/has been edited since/)).not.toBeInTheDocument();
  });

  it("offers to analyse again", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByRole("button", { name: /analyse again/i })).toBeInTheDocument();
  });

  it("offers earlier readings once there is more than one", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ analysis: analysis({ version: 2 }), available_versions: [2, 1] })),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v2" })).toBeInTheDocument();
  });

  it("hides the version picker when there is only one reading", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText("Python");

    expect(screen.queryByText(/Earlier readings/)).not.toBeInTheDocument();
  });

  it("requests an older version when one is picked", async () => {
    const fetchMock = routes(
      view({ analysis: analysis({ version: 2 }), available_versions: [2, 1] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByRole("button", { name: "v1" });

    await userEvent.click(screen.getByRole("button", { name: "v1" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("version=1"))).toBe(true);
    });
  });

  it("says which version is being read when it is not the latest", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ analysis: analysis({ version: 1 }), available_versions: [2, 1] })),
    );

    renderWithQuery(<JobIntelligence job={job()} />);

    expect(await screen.findByText(/reading version 1 of 2/)).toBeInTheDocument();
  });
});

// --- what must not appear -----------------------------------------------------

describe("what this phase does not show", () => {
  it("shows no match score, gaps, recommendation, or application data", async () => {
    // None of it exists. An empty version of each would read as a broken
    // product rather than an unbuilt one.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobIntelligence job={job()} />);
    await screen.findByText("Python");

    for (const absent of [
      /match score/i,
      /your gaps/i,
      /recommend/i,
      /resume strategy/i,
      /application status/i,
      /% match/i,
    ]) {
      expect(screen.queryByText(absent)).not.toBeInTheDocument();
    }
  });
});
