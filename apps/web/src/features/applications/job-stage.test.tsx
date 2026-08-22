import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobApplicationPanel } from "@/features/applications/job-application-panel";

/**
 * Moving an application between stages, from the job screen.
 *
 * The control this replaces was a native `<select>` holding `value=""` and
 * mutating on `change`. It had no test, which is how it kept two defects at
 * once: it never showed where the application actually was, and arrow-keying
 * through it fired a transition per option.
 *
 * The second is the one worth a file. Application status is append-only and
 * every move writes an event, so walking the list with a keyboard did not waste
 * requests — it wrote a career history of things that never happened, on behalf
 * of somebody who was only looking.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const JOB = {
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
} as never;

function application(overrides: Record<string, unknown> = {}) {
  return {
    id: "app-1",
    job_id: "job-1",
    status: "APPLIED",
    job_title: "Senior Backend Engineer",
    company: "Verdant",
    notes: null,
    allowed_transitions: ["HR_SCREEN", "TECHNICAL_INTERVIEW", "REJECTED"],
    days_in_stage: 4,
    resume_version_id: null,
    source: null,
    applied_at: "2026-08-01T00:00:00Z",
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function server(rows: unknown[]) {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({
      url: String(url),
      method,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    if (method !== "GET") {
      return { ok: true, status: 200, json: async () => ({ data: application() }) };
    }
    return { ok: true, status: 200, json: async () => ({ data: rows }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function moves(calls: Array<{ method: string }>) {
  return calls.filter((call) => call.method !== "GET").length;
}

afterEach(() => vi.unstubAllGlobals());

describe("moving an application between stages", () => {
  it("says where the application is now", async () => {
    // The control that moves you somewhere also has to say where you are. The
    // select it replaces showed "Choose a stage…" and never the current one.
    server([application({ status: "APPLIED" })]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);

    /* Asserted through the group's accessible name rather than the paragraph.
       The buttons are labelled by that line, so this is the sentence a screen
       reader actually hears before it is offered anywhere to go. */
    expect(await screen.findByRole("group")).toHaveAccessibleName(/Now at Applied/);
  });

  it("offers exactly the transitions the server allows", async () => {
    server([application()]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);
    const group = await screen.findByRole("group");

    for (const stage of ["HR screen", "Technical interview", "Rejected"]) {
      expect(within(group).getByRole("button", { name: stage })).toBeInTheDocument();
    }
  });

  it("moves once, when a stage is chosen deliberately", async () => {
    const calls = server([application()]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);
    const group = await screen.findByRole("group");
    await userEvent.click(within(group).getByRole("button", { name: "Technical interview" }));

    await waitFor(() => expect(moves(calls)).toBe(1));
    expect(calls.find((call) => call.method !== "GET")?.body).toMatchObject({
      status: "TECHNICAL_INTERVIEW",
    });
  });

  it("writes nothing while a keyboard is passing through", async () => {
    /* The defect, as a test. A native select fires `change` per option under
       arrow keys, and each one here is an append-only status transition — so a
       reader tabbing to "Rejected" would have posted an HR screen and a
       technical interview that never happened. */
    const calls = server([application()]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);
    const group = await screen.findByRole("group");

    within(group).getByRole("button", { name: "HR screen" }).focus();
    await userEvent.keyboard("{Tab}{Tab}");

    expect(moves(calls)).toBe(0);
  });

  it("remembers what was sent, not only when", async () => {
    /* docs/07 names four things to preserve when a user applies: the date, the
       exact resume version, the source, and any notes. The card kept the first
       and dropped the rest, though the form had collected them on the way in.

       The version is the one that decays. A resume is edited after it is sent,
       so within a week "which one did they actually see" stops being
       answerable from the current document. */
    const calls = server([application({ resume_version_id: "ver-1", source: "COMPANY_WEBSITE" })]);
    void calls;

    renderWithQuery(<JobApplicationPanel job={JOB} />);

    expect(await screen.findByText("Resume")).toBeInTheDocument();
    expect(screen.getByText("Through")).toBeInTheDocument();
    expect(screen.getByText("Company website")).toBeInTheDocument();
  });

  it("says a fact was not recorded rather than leaving a gap", async () => {
    /* "Not recorded" is a fact about the application — the form offers it and
       somebody chose it. A blank would read as the record having lost
       something. */
    server([application({ resume_version_id: null, source: null })]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);
    await screen.findByText("Resume");

    expect(screen.getAllByText("Not recorded")).toHaveLength(2);
  });

  it("says nothing about sending until something has been sent", async () => {
    server([application({ applied_at: null, status: "READY_TO_APPLY" })]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);
    await screen.findByText(/Now at/);

    expect(screen.queryByText("Through")).not.toBeInTheDocument();
  });

  it("says so when there is nowhere left to go", async () => {
    /* Rather than rendering nothing. A row of buttons that simply stops
       appearing reads as a screen that failed to load them. */
    server([application({ status: "ARCHIVED", allowed_transitions: [] })]);

    renderWithQuery(<JobApplicationPanel job={JOB} />);

    expect(await screen.findByText(/nowhere further to go/)).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});
