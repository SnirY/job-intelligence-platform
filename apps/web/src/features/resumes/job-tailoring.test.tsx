import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobTailoringPanel } from "@/features/resumes/job-tailoring";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function job() {
  return {
    id: "job-1",
    title: "Senior Backend Engineer",
    company: "Verdant",
    status: "ANALYZED",
  } as never;
}

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: "strategy-1",
    job_id: "job-1",
    match_id: "match-1",
    version: 1,
    version_id: null,
    summary: "Lead with the Python routing work.",
    emphasize: ["Python"],
    reduce: ["Frontend work"],
    reorder_note: null,
    priority_projects: [],
    missing_evidence: ["Your mentoring achievement is not on this resume."],
    career_gaps: ["No Kubernetes anywhere in your profile."],
    selection: {},
    model: null,
    prompt_version: null,
    warnings: [],
    created_at: "2026-07-29T00:00:00Z",
    ...overrides,
  };
}

function claim(overrides: Record<string, unknown> = {}) {
  return {
    id: "claim-1",
    text: "40%",
    status: "BLOCKED",
    explanation: "“40%” does not appear anywhere in your profile.",
    confidence: 95,
    ...overrides,
  };
}

function suggestion(overrides: Record<string, unknown> = {}) {
  return {
    id: "suggestion-1",
    item_id: "item-1",
    suggestion_type: "REWRITE",
    status: "PENDING",
    risk: "LOW",
    original_text: "Improved the routing service.",
    suggested_text: "Improved routing service throughput.",
    final_text: null,
    rationale: "Closer to the posting's language.",
    display_order: 0,
    claims: [],
    requires_review: false,
    is_blocked: false,
    ...overrides,
  };
}

function view(overrides: Record<string, unknown> = {}) {
  return {
    strategy: strategy(),
    suggestions: [suggestion()],
    blocked_count: 0,
    can_create: true,
    blocking_reason: null,
    suggestions_generated: true,
    ...overrides,
  };
}

/** Dispatches on the URL: the panel also reads the resume and version lists. */
function routes(payload: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  const resumes = extra.resumes ?? [{ id: "resume-1", title: "Backend Engineer", family: "BASE" }];
  const versions = extra.versions ?? [{ id: "version-1", version: 1, status: "DRAFT" }];

  return vi.fn(async (url: string) => {
    const path = String(url);
    let data: unknown = payload;
    if (path.includes("/versions")) data = versions;
    else if (path.includes("/resumes")) data = resumes;

    return { ok: true, status: 200, json: async () => ({ data }) };
  });
}

afterEach(() => vi.unstubAllGlobals());

// --- before there is a plan -------------------------------------------------------

describe("before there is a plan", () => {
  it("offers to plan one", async () => {
    vi.stubGlobal("fetch", routes(view({ strategy: null, suggestions: [] })));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/No tailoring plan for this job yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /plan a tailored resume/i })).toBeEnabled();
  });

  it("will not offer to plan for a job that has never been matched", async () => {
    // The strategy answers "which real career gaps remain", and that is match
    // data. Offering the button anyway would promise something the API refuses.
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          strategy: null,
          suggestions: [],
          can_create: false,
          blocking_reason: "This job has not been matched against your profile yet.",
        }),
      ),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByRole("button", { name: /plan a tailored resume/i })).toBeDisabled();
    expect(screen.getByText(/has not been matched/)).toBeInTheDocument();
  });
});

// --- the plan ---------------------------------------------------------------------

describe("the plan", () => {
  it("keeps a resume gap and a career gap apart", async () => {
    // docs/06-resume-engine.md insists on the distinction: one is fixable by
    // selecting differently, the other is not fixable by any amount of writing.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText("In your profile, not on this resume")).toBeInTheDocument();
    expect(screen.getByText("Not in your profile at all")).toBeInTheDocument();
    expect(screen.getByText(/No rewriting fixes this one/)).toBeInTheDocument();
  });

  it("shows what to lead with and what to cut", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText("Lead with")).toBeInTheDocument();
    expect(screen.getByText("Cut back")).toBeInTheDocument();
  });

  it("surfaces a warning when the written plan could not be generated", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          strategy: strategy({
            summary: null,
            warnings: [
              "A written plan could not be generated, so this strategy shows the selected evidence only.",
            ],
          }),
        }),
      ),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/written plan could not be generated/)).toBeInTheDocument();
  });

  it("renders two identical warnings rather than collapsing them to one", async () => {
    // Found 2026-08-11. The list keyed each item by its own text, so React saw
    // a duplicate key — it warns in development and drops a row in production.
    // The duplicate itself is fixed server-side, but a list whose identity
    // depends on its content being unique is one dedupe bug away from silently
    // losing a line, and losing a warning is the worst thing this list can do.
    const repeated = "Suggestions could not be generated. Your resume is unchanged.";
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          strategy: strategy({ summary: null, warnings: [repeated, repeated] }),
        }),
      ),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findAllByText(repeated)).toHaveLength(2);
  });
});

// --- reviewing suggestions ----------------------------------------------------------

describe("reviewing suggestions", () => {
  it("shows what a change would replace", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText("Improved the routing service.")).toBeInTheDocument();
    expect(screen.getByText("Improved routing service throughput.")).toBeInTheDocument();
  });

  it("names an unsupported claim rather than only marking the line", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          suggestions: [
            suggestion({
              risk: "HIGH",
              requires_review: true,
              is_blocked: true,
              suggested_text: "Improved routing service performance by 40%.",
              claims: [claim()],
            }),
          ],
          blocked_count: 1,
        }),
      ),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/does not appear anywhere in your profile/)).toBeInTheDocument();
    expect(screen.getByText("Not supported:")).toBeInTheDocument();
  });

  it("tells the user to add a real figure to the profile rather than only the resume", async () => {
    // docs/06: the system may ask for a missing metric; it must never make
    // one up, and the fix is the profile, not this one document.
    vi.stubGlobal(
      "fetch",
      routes(view({ suggestions: [suggestion({ is_blocked: true })], blocked_count: 1 })),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/add it to your profile/)).toBeInTheDocument();
  });

  it("labels risk in words rather than colour alone", async () => {
    vi.stubGlobal("fetch", routes(view({ suggestions: [suggestion({ risk: "HIGH" })] })));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText("Check carefully")).toBeInTheDocument();
  });

  it("accepts one suggestion at a time", async () => {
    const fetchMock = routes(view());
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobTailoringPanel job={job()} />);
    await screen.findByText("Improved routing service throughput.");

    await userEvent.click(screen.getByRole("button", { name: /accept/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith("/suggestion-1/accept")),
      ).toBe(true);
    });
  });

  it("rejects without changing anything", async () => {
    const fetchMock = routes(view());
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobTailoringPanel job={job()} />);
    await screen.findByText("Improved routing service throughput.");

    await userEvent.click(screen.getByRole("button", { name: /reject/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith("/suggestion-1/reject")),
      ).toBe(true);
    });
  });

  it("lets the user supply their own wording", async () => {
    const fetchMock = routes(view());
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobTailoringPanel job={job()} />);
    await screen.findByText("Improved routing service throughput.");

    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    await userEvent.click(screen.getByRole("button", { name: /use my wording/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/suggestion-1/edit"))).toBe(
        true,
      );
    });
  });

  it("offers no decision on a suggestion already decided", async () => {
    vi.stubGlobal("fetch", routes(view({ suggestions: [suggestion({ status: "ACCEPTED" })] })));

    renderWithQuery(<JobTailoringPanel job={job()} />);
    await screen.findByText("Improved routing service throughput.");

    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reject/i })).not.toBeInTheDocument();
  });
});

// --- finalising ---------------------------------------------------------------------

describe("finalising", () => {
  it("says that a pending suggestion is left alone", async () => {
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/anything still pending is left alone/)).toBeInTheDocument();
  });

  it("reports how much of the review is done", async () => {
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          suggestions: [
            suggestion({ status: "ACCEPTED" }),
            suggestion({ id: "suggestion-2", item_id: "item-2" }),
          ],
        }),
      ),
    );

    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/1 of 2 reviewed/)).toBeInTheDocument();
  });
});

// --- what the phase does not do -------------------------------------------------------

describe("what tailoring never does", () => {
  it("offers no one-click rewrite of the whole document", async () => {
    // docs/09-mvp-roadmap.md: tailoring is incomplete if one call rewrites the
    // document. The four stages are four visible steps.
    vi.stubGlobal("fetch", routes(view()));

    renderWithQuery(<JobTailoringPanel job={job()} />);
    await screen.findByText("Suggestions");

    for (const absent of [/apply all/i, /accept all/i, /rewrite my resume/i, /auto-tailor/i]) {
      expect(screen.queryByRole("button", { name: absent })).not.toBeInTheDocument();
    }
  });
});

// --- Stage 2.8.6 ---------------------------------------------------------------
//
// Both of these were found by walking the panel with a real posting, and
// neither was visible to the sixteen tests above.

describe("a run that proposed nothing", () => {
  it("says so, instead of looking like a button that was never pressed", async () => {
    vi.stubGlobal("fetch", routes(view({ suggestions: [], suggestions_generated: true })));
    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/nothing to change/i)).toBeInTheDocument();
    // The pre-run wording must be gone, or the two states still read alike.
    expect(screen.queryByText(/no suggestions yet/i)).not.toBeInTheDocument();
  });

  it("still asks for a run when none has happened", async () => {
    vi.stubGlobal("fetch", routes(view({ suggestions: [], suggestions_generated: false })));
    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText(/no suggestions yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing to change/i)).not.toBeInTheDocument();
  });
});

describe("a suggestion that changes no words", () => {
  it("does not strike out the line and print it back unchanged", async () => {
    // A real REORDER from the walkthrough: the education line keeps its exact
    // wording and moves up the page. Rendered as a diff it read as
    // "delete this, then restore it".
    const text = "B.Sc. in Software Engineering, [engineering college]";
    vi.stubGlobal(
      "fetch",
      routes(
        view({
          suggestions: [
            suggestion({
              suggestion_type: "REORDER",
              original_text: text,
              suggested_text: text,
            }),
          ],
        }),
      ),
    );
    renderWithQuery(<JobTailoringPanel job={job()} />);

    const shown = await screen.findAllByText(text);
    expect(shown).toHaveLength(1);
    expect(shown[0]!.className).not.toContain("line-through");
  });

  it("names the kind of change, so a move reads as a move", async () => {
    vi.stubGlobal(
      "fetch",
      routes(view({ suggestions: [suggestion({ suggestion_type: "REORDER" })] })),
    );
    renderWithQuery(<JobTailoringPanel job={job()} />);

    expect(await screen.findByText("Move this earlier")).toBeInTheDocument();
  });
});
