import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobDetail } from "@/features/jobs/job-detail";

/**
 * Deleting a job, which until now nothing asserted at all.
 *
 * F29 recorded the missing dialog. Writing these found the other half: there
 * was no test file for `job-detail.tsx`, so the single most destructive action
 * in the product had never had a line written about it. The confirmation is
 * only half of what was missing.
 *
 * What is asserted here is the contract rather than the wording. That a click
 * asks instead of doing; that the question names what goes; that Escape and the
 * backdrop resolve the safe way; and that focus behaves — which is the half
 * nobody sees in a screenshot and the half that was wrong last time.
 */

const push = vi.fn();

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

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
};

/**
 * One fetch mock for the whole detail page.
 *
 * It composes six panels and each runs its own queries. Everything not named
 * here answers with an empty envelope rather than a failure, so a panel this
 * file is not about cannot turn into a red test about deletion.
 */
function server(
  options: {
    job?: Record<string, unknown>;
    readings?: number;
    matches?: number;
    tracked?: boolean;
    deleteFails?: boolean;
  } = {},
) {
  const { job = JOB, readings = 0, matches = 0, tracked = false, deleteFails = false } = options;

  const calls: Array<{ url: string; method: string }> = [];

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(url);
    calls.push({ url: path, method });

    const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => ({ data }) });

    if (method === "DELETE") {
      return deleteFails
        ? { ok: false, status: 500, json: async () => ({ error: { message: "no" } }) }
        : { ok: true, status: 204, json: async () => ({ data: null }) };
    }

    if (path.includes("/analysis")) {
      return ok({
        job_id: "job-1",
        job_status: "ANALYZED",
        analysis: null,
        requirements: [],
        responsibilities: [],
        processing: null,
        is_stale: false,
        available_versions: Array.from({ length: readings }, (_, i) => i + 1),
        can_analyze: true,
      });
    }

    if (path.includes("/match")) {
      return ok({
        job_id: "job-1",
        match: null,
        items: [],
        is_stale: false,
        stale_reasons: [],
        available_versions: Array.from({ length: matches }, (_, i) => i + 1),
        can_match: true,
        blocking_reason: null,
        preference_fit: [],
      });
    }

    if (path.includes("/applications")) {
      return ok(
        tracked
          ? [
              {
                id: "app-1",
                job_id: "job-1",
                status: "HR_SCREEN",
                job_title: "Senior Backend Engineer",
                company: "Verdant",
                notes: null,
                allowed_transitions: [],
                days_in_stage: 4,
                applied_at: null,
                archived_at: null,
                created_at: "2026-08-01T00:00:00Z",
                updated_at: "2026-08-01T00:00:00Z",
              },
            ]
          : [],
      );
    }

    if (path.includes("/jobs/job-1")) return ok(job);

    return ok([]);
  });

  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function deleted(calls: Array<{ url: string; method: string }>) {
  return calls.some((call) => call.method === "DELETE");
}

async function openTheDialog() {
  const opener = await screen.findByRole("button", { name: /delete permanently/i });
  await userEvent.click(opener);
  return { opener, dialog: await screen.findByRole("alertdialog") };
}

beforeEach(() => push.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("deleting a job", () => {
  it("asks before it deletes", async () => {
    // F29. One click, no dialog, no undo, no way back.
    const { calls } = server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    await openTheDialog();

    expect(deleted(calls)).toBe(false);
  });

  it("says what goes with it, not just that something will", async () => {
    /* "Are you sure?" transfers responsibility without transferring
       information. A job is not one row: the readings of the posting, the
       matches computed against it and the application tracked from it all go,
       and none of that is visible from a button. */
    server({ readings: 2, matches: 3, tracked: true });

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    expect(within(dialog).getByText(/2 readings of the posting/)).toBeInTheDocument();
    expect(within(dialog).getByText(/3 matches and the evidence behind them/)).toBeInTheDocument();
    expect(within(dialog).getByText(/application you are tracking/)).toBeInTheDocument();
  });

  it("counts nothing it cannot count", async () => {
    /* A job with no analysis gets a shorter sentence rather than a hedged one.
       A warning that lists things which might exist is the kind people learn
       to skip, and then the one that mattered goes past too. */
    server({ readings: 0, matches: 0, tracked: false });

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    expect(within(dialog).getByText(/cannot be undone/i)).toBeInTheDocument();
    expect(within(dialog).queryByText(/readings of the posting/)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/application you are tracking/)).not.toBeInTheDocument();
  });

  it("deletes and leaves the page once confirmed", async () => {
    const { calls } = server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    await userEvent.click(within(dialog).getByRole("button", { name: /delete permanently/i }));

    await waitFor(() => expect(deleted(calls)).toBe(true));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/jobs"));
  });

  it("deletes nothing when cancelled", async () => {
    const { calls } = server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleted(calls)).toBe(false);
  });

  it("treats Escape as cancel", async () => {
    // The key people press when they are not sure has to resolve the safe way.
    const { calls } = server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    await openTheDialog();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleted(calls)).toBe(false);
  });

  it("offers the reversible thing instead", async () => {
    /* The reason a confirmation belongs here and not on bulk archive: archive
       is reversible and delete is not. Saying so is cheaper than the dialog
       that only says no. */
    const { calls } = server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    await userEvent.click(within(dialog).getByRole("button", { name: /archive instead/i }));

    await waitFor(() => expect(calls.some((c) => c.url.includes("/archive"))).toBe(true));
    expect(deleted(calls)).toBe(false);
  });

  it("does not offer to archive something already archived", async () => {
    // A button that does nothing, in the dialog whose whole job is to be believed.
    server({ job: { ...JOB, archived_at: "2026-08-01T00:00:00Z" } });

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    expect(
      within(dialog).queryByRole("button", { name: /archive instead/i }),
    ).not.toBeInTheDocument();
  });
});

describe("the dialog's focus", () => {
  it("does not open with the destructive button under the cursor", async () => {
    /* A dialog that arrives focused on Delete has turned Enter into the thing
       it was put there to prevent. */
    server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
  });

  it("returns focus to whatever opened it", async () => {
    // F31, recorded against the mobile drawer: a dialog that takes focus and
    // does not give it back leaves a keyboard reader at the top of the
    // document.
    server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { opener, dialog } = await openTheDialog();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(document.activeElement).toBe(opener);
  });

  it("keeps Tab inside while it is open", async () => {
    /* aria-modal promises a screen reader that what is behind is unreachable.
       Tab running onto the page underneath makes that promise false, which is
       worse than never making it. */
    server();

    renderWithQuery(<JobDetail jobId="job-1" />);
    const { dialog } = await openTheDialog();

    for (let press = 0; press < 8; press += 1) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});
