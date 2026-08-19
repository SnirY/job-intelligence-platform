import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddJobForm } from "@/features/jobs/add-job-form";
import { JobDetail } from "@/features/jobs/job-detail";
import { JobsList } from "@/features/jobs/jobs-list";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function ok(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

function page(rows: unknown[], meta: Record<string, number> = {}) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data: rows,
      meta: {
        page: 1,
        page_size: 20,
        total: rows.length,
        total_pages: rows.length ? 1 : 0,
        ...meta,
      },
    }),
  };
}

function conflict(details: Record<string, string>) {
  return {
    ok: false,
    status: 409,
    json: async () => ({
      error: { code: "CONFLICT", message: "You have already saved this job.", details },
    }),
  };
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    title: "Senior Backend Engineer",
    company: "Verdant Logistics",
    location: "Lisbon",
    work_mode: "HYBRID",
    employment_type: "FULL_TIME",
    seniority: "SENIOR",
    status: "RAW",
    import_method: "PASTED_DESCRIPTION",
    source_url: null,
    archived_at: null,
    created_at: "2026-07-27T00:00:00Z",
    has_description: true,
    ...overrides,
  };
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    ...summary(),
    description: "We are hiring a backend engineer.",
    role_family: null,
    notes: null,
    salary_text: null,
    fetch_error: null,
    updated_at: "2026-07-27T00:00:00Z",
    ...overrides,
  };
}

/** Routes fetches by URL, since each screen makes more than one call. */
function routes(handlers: Record<string, unknown>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    if (url.includes("/companies")) return ok(handlers.companies ?? []);
    if (url.includes("/source")) return ok(handlers.source);
    // Job Detail mounts a panel per phase, and each reads its own collection.
    // Falling through to `handlers.job` would hand a list endpoint a single
    // object — which is not a shape the API can ever return, so a component
    // crashing on it says more about this mock than about the component.
    if (url.includes("/applications")) return ok(handlers.applications ?? []);
    if (url.includes("/resume")) return ok(handlers.resumes ?? []);
    if (url.includes("/jobs/archive"))
      return ok(handlers.bulkArchive ?? { archived: [], missing: [] });
    // The list is the only call with a query string or a bare /jobs path.
    if (/\/jobs(\?|$)/.test(url)) return handlers.list ?? page([]);
    return ok(handlers.job);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

// --- list ---------------------------------------------------------------------

describe("jobs list", () => {
  it("invites a first job when nothing is saved", async () => {
    vi.stubGlobal("fetch", routes({ list: page([]) }));

    renderWithQuery(<JobsList />);

    expect(await screen.findByText(/Add your first job/)).toBeInTheDocument();
  });

  it("shows a loading state before results arrive", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderWithQuery(<JobsList />);

    expect(screen.getByText(/Loading your jobs/)).toBeInTheDocument();
  });

  it("surfaces a load failure rather than an empty list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<JobsList />);

    expect(await screen.findByText(/Could not load your jobs/)).toBeInTheDocument();
  });

  it("offers one action for a selection, naming how many", async () => {
    vi.stubGlobal(
      "fetch",
      routes({ list: page([summary(), summary({ id: "job-2", title: "Platform Engineer" })]) }),
    );

    renderWithQuery(<JobsList />);

    const first = await screen.findByRole("checkbox", { name: /Select Senior Backend Engineer/ });
    await userEvent.click(first);

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Archive 1/ })).toBeInTheDocument();
  });

  it("archives the selection in one call rather than one call per row", async () => {
    /* Twenty-nine rows must not be twenty-nine round trips asking the same
       ownership question. */
    const fetchMock = routes({
      list: page([summary(), summary({ id: "job-2", title: "Platform Engineer" })]),
      bulkArchive: { archived: ["job-1", "job-2"], missing: [] },
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);

    await userEvent.click(
      await screen.findByRole("checkbox", { name: /Select Senior Backend Engineer/ }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Platform Engineer/ }));
    await userEvent.click(screen.getByRole("button", { name: /Archive 2/ }));

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/jobs/archive"));
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ job_ids: ["job-1", "job-2"] });
  });

  it("names what it could not archive instead of reporting a bare count", async () => {
    /* The call is not atomic on purpose, so a partial result is the ordinary
       outcome. "1 archived" with no way to see which one failed would send
       someone back to reselect the rows to find out. */
    vi.stubGlobal(
      "fetch",
      routes({
        list: page([summary(), summary({ id: "job-2", title: "Platform Engineer" })]),
        bulkArchive: { archived: ["job-1"], missing: ["job-2"] },
      }),
    );

    renderWithQuery(<JobsList />);

    await userEvent.click(
      await screen.findByRole("checkbox", { name: /Select Senior Backend Engineer/ }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Platform Engineer/ }));
    await userEvent.click(screen.getByRole("button", { name: /Archive 2/ }));

    expect(await screen.findByText(/1 job archived/)).toBeInTheDocument();
    // Scoped to the outcome: the title is also on the row it failed to archive,
    // which is the point — that row is still in the list.
    expect(screen.getByText(/could not be archived/)).toHaveTextContent("Platform Engineer");
  });

  it("keeps the outcome on screen until it is dismissed", async () => {
    /* Not a toast: the result of an action on a page of rows is not something
       a reader should have five seconds to catch. */
    vi.stubGlobal(
      "fetch",
      routes({ list: page([summary()]), bulkArchive: { archived: ["job-1"], missing: [] } }),
    );

    renderWithQuery(<JobsList />);

    await userEvent.click(
      await screen.findByRole("checkbox", { name: /Select Senior Backend Engineer/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: /Archive 1/ }));

    const outcome = await screen.findByText(/1 job archived/);
    expect(outcome).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/1 job archived/)).not.toBeInTheDocument();
  });

  it("lists jobs with their facts", async () => {
    vi.stubGlobal("fetch", routes({ list: page([summary()]) }));

    renderWithQuery(<JobsList />);

    expect(await screen.findByText("Senior Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Verdant Logistics · Lisbon · Hybrid/)).toBeInTheDocument();
  });

  it("distinguishes no results from no jobs", async () => {
    // Telling a user with forty jobs that they have none would read as data
    // loss rather than as a filter that matched nothing.
    vi.stubGlobal("fetch", routes({ list: page([]) }));

    renderWithQuery(<JobsList />);
    await screen.findByText(/Add your first job/);

    await userEvent.type(screen.getByLabelText("Search"), "nothing");

    expect(await screen.findByText(/No jobs match those filters/)).toBeInTheDocument();
  });

  it("sends the search term to the API", async () => {
    const fetchMock = routes({ list: page([summary()]) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.type(screen.getByLabelText("Search"), "backend");

    await waitFor(() => {
      const searched = fetchMock.mock.calls.some(([url]) => String(url).includes("search=backend"));
      expect(searched).toBe(true);
    });
  });

  it("sends the chosen sort", async () => {
    const fetchMock = routes({ list: page([summary()]) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.selectOptions(screen.getByLabelText("Sort"), "TITLE");

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("sort=TITLE"))).toBe(true);
    });
  });

  it("sends a work mode filter", async () => {
    const fetchMock = routes({ list: page([summary()]) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.selectOptions(screen.getByLabelText("Work mode"), "REMOTE");

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("work_mode=REMOTE"))).toBe(
        true,
      );
    });
  });

  it("does not send a filter the user cleared", async () => {
    // An empty select means "no filter", not "jobs whose work mode is empty".
    const fetchMock = routes({ list: page([summary()]) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("work_mode="))).toBe(true);
  });

  it("pages through results", async () => {
    const fetchMock = routes({
      list: page([summary()], { total: 40, total_pages: 2, page_size: 20 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("page=2"))).toBe(true);
    });
  });

  it("hides the pager when everything fits on one page", async () => {
    vi.stubGlobal("fetch", routes({ list: page([summary()]) }));

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    expect(screen.queryByRole("button", { name: /next/i })).not.toBeInTheDocument();
  });

  it("shows a job that is still being fetched", async () => {
    vi.stubGlobal("fetch", routes({ list: page([summary({ status: "FETCHING" })]) }));

    renderWithQuery(<JobsList />);

    expect(await screen.findByText(/Reading the page/)).toBeInTheDocument();
  });

  it("flags a job whose import failed", async () => {
    vi.stubGlobal("fetch", routes({ list: page([summary({ status: "FAILED" })]) }));

    renderWithQuery(<JobsList />);

    expect(await screen.findByText(/Needs a description/)).toBeInTheDocument();
  });

  it("shows no status badge for an ordinary saved job", async () => {
    // A badge on every row is noise that makes the two states worth noticing
    // invisible.
    vi.stubGlobal("fetch", routes({ list: page([summary()]) }));

    renderWithQuery(<JobsList />);
    await screen.findByText("Senior Backend Engineer");

    expect(screen.queryByText(/Reading the page|Needs a description/)).not.toBeInTheDocument();
  });
});

// --- add ----------------------------------------------------------------------

describe("add job", () => {
  it("offers all three ways to add a job", () => {
    vi.stubGlobal("fetch", routes({}));

    renderWithQuery(<AddJobForm />);

    expect(screen.getByRole("button", { name: /paste the description/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /import from a link/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /type the details/i })).toBeInTheDocument();
  });

  it("asks only for a link when importing from a URL", async () => {
    vi.stubGlobal("fetch", routes({}));

    renderWithQuery(<AddJobForm />);
    await userEvent.click(screen.getByRole("button", { name: /import from a link/i }));

    expect(screen.getByLabelText("Job URL")).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
  });

  it("keeps save disabled until a pasted job has what it needs", async () => {
    vi.stubGlobal("fetch", routes({}));

    renderWithQuery(<AddJobForm />);

    const save = screen.getByRole("button", { name: /save job/i });
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Description"), "We are hiring.");
    expect(save).toBeEnabled();
  });

  it("lets a manual job be saved without a description", async () => {
    vi.stubGlobal("fetch", routes({}));

    renderWithQuery(<AddJobForm />);
    await userEvent.click(screen.getByRole("button", { name: /type the details/i }));
    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");

    expect(screen.getByRole("button", { name: /save job/i })).toBeEnabled();
  });

  it("posts a pasted job and opens it", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      void init;
      return { ok: true, status: 201, json: async () => ({ data: job() }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<AddJobForm />);
    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");
    await userEvent.type(screen.getByLabelText("Description"), "We are hiring.");
    await userEvent.click(screen.getByRole("button", { name: /save job/i }));

    await waitFor(() => {
      const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
      expect(body.import_method).toBe("PASTED_DESCRIPTION");
      expect(body.title).toBe("Backend Engineer");
      expect(body.allow_duplicate).toBe(false);
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/jobs/job-1"));
  });

  it("names the job a duplicate matched instead of just refusing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        conflict({
          existing_job_id: "job-9",
          existing_title: "Senior Backend Engineer",
          reason: "SAME_CONTENT",
        }),
      ),
    );

    renderWithQuery(<AddJobForm />);
    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");
    await userEvent.type(screen.getByLabelText("Description"), "We are hiring.");
    await userEvent.click(screen.getByRole("button", { name: /save job/i }));

    // A bare 409 would leave the user unable to find the job they supposedly
    // already have.
    expect(await screen.findByText(/You may already have this job/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Senior Backend Engineer" })).toHaveAttribute(
      "href",
      "/jobs/job-9",
    );
    expect(screen.getByText(/the same description/)).toBeInTheDocument();
  });

  it("resubmits with allow_duplicate when the user insists", async () => {
    let call = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      void url;
      void init;
      call += 1;
      return call === 1
        ? conflict({
            existing_job_id: "job-9",
            existing_title: "Existing",
            reason: "SAME_URL",
          })
        : { ok: true, status: 201, json: async () => ({ data: job() }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<AddJobForm />);
    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");
    await userEvent.type(screen.getByLabelText("Description"), "We are hiring.");
    await userEvent.click(screen.getByRole("button", { name: /save job/i }));

    await screen.findByText(/You may already have this job/);
    await userEvent.click(screen.getByRole("button", { name: /add it anyway/i }));

    await waitFor(() => {
      const body = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
      expect(body.allow_duplicate).toBe(true);
    });
  });

  it("reports an ordinary failure without claiming anything was saved", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<AddJobForm />);
    await userEvent.type(screen.getByLabelText("Title"), "Backend Engineer");
    await userEvent.type(screen.getByLabelText("Description"), "We are hiring.");
    await userEvent.click(screen.getByRole("button", { name: /save job/i }));

    expect(await screen.findByText(/Could not save that job/)).toBeInTheDocument();
  });

  it("shows the reason a blocked link was refused, and keeps the user on the form", async () => {
    /* DEV-041. These used to be saved, queued, failed, and then presented on a
       job page offering "paste the description" and "Try the link again" —
       neither of which can help, because the block is on the address and the
       SSRF rules are deliberately not configurable.

       The refusal now arrives as a 422 the form already knows how to show, so
       the user reads the reason with their URL still in the box. */
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "BLOCKED_URL",
              message: "That link points somewhere we will not fetch from.",
              details: { source_url: "http://169.254.169.254/" },
              request_id: null,
            },
          }),
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    renderWithQuery(<AddJobForm />);
    await userEvent.click(screen.getByRole("button", { name: /import from a link/i }));
    await userEvent.type(screen.getByLabelText(/job url/i), "http://169.254.169.254/");
    await userEvent.click(screen.getByRole("button", { name: /save job/i }));

    expect(await screen.findByText(/points somewhere we will not fetch from/i)).toBeInTheDocument();
    // The generic copy would tell them to check their connection, which is the
    // one thing that cannot be the problem here.
    expect(screen.queryByText(/Check your connection/i)).not.toBeInTheDocument();
  });
});

// --- detail -------------------------------------------------------------------

describe("job detail", () => {
  it("shows the job and its details", async () => {
    vi.stubGlobal("fetch", routes({ job: job() }));

    renderWithQuery(<JobDetail jobId="job-1" />);

    expect(await screen.findByRole("heading", { name: "Senior Backend Engineer" })).toBeVisible();
    expect(screen.getByText("Lisbon")).toBeInTheDocument();
    expect(screen.getByText("We are hiring a backend engineer.")).toBeInTheDocument();
  });

  it("shows nothing that does not exist yet", async () => {
    // Requirements, recommendations, match verdicts, and now resume tailoring
    // all arrived with Phases 5 to 7 and are legitimately on this screen. What
    // is still unbuilt must stay absent — an empty version of it would read as
    // broken rather than as forthcoming.
    vi.stubGlobal("fetch", routes({ job: job() }));

    renderWithQuery(<JobDetail jobId="job-1" />);
    await screen.findByRole("heading", { name: "Senior Backend Engineer" });

    for (const absent of [/application status/i, /mark as applied/i, /career impact/i]) {
      expect(screen.queryByText(absent)).not.toBeInTheDocument();
    }
  });

  it("explains a job that does not exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({ error: { code: "NOT_FOUND", message: "Job not found." } }),
      })),
    );

    renderWithQuery(<JobDetail jobId="missing" />);

    expect(await screen.findByText(/does not exist, or is not yours/)).toBeInTheDocument();
  });

  it("says a URL import is in progress", async () => {
    vi.stubGlobal("fetch", routes({ job: job({ status: "FETCHING", description: null }) }));

    renderWithQuery(<JobDetail jobId="job-1" />);

    expect(await screen.findByText(/Reading the posting/)).toBeInTheDocument();
  });

  it("offers the paste fallback when a fetch failed", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        job: job({
          status: "FAILED",
          description: null,
          fetch_error: "That page could not be reached.",
          source_url: "https://jobs.example.com/role",
        }),
      }),
    );

    renderWithQuery(<JobDetail jobId="job-1" />);

    // GOAL.md: a failure must leave the resource usable, and the user has to be
    // told that or they will start over.
    expect(await screen.findByText(/Your job is saved/)).toBeInTheDocument();
    expect(screen.getByLabelText("Job description")).toBeInTheDocument();
    expect(screen.getByText(/could not be reached/)).toBeInTheDocument();
  });

  it("posts a hand-supplied description", async () => {
    const fetchMock = routes({
      job: job({ status: "FAILED", description: null, source_url: "https://x.example.com/r" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobDetail jobId="job-1" />);
    await screen.findByLabelText("Job description");

    await userEvent.type(screen.getByLabelText("Job description"), "Pasted description.");
    await userEvent.click(screen.getByRole("button", { name: /save description/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/description"));
      expect(JSON.parse(String(call?.[1]?.body)).description).toBe("Pasted description.");
    });
  });

  it("offers a retry when the job still has a link", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        job: job({ status: "FAILED", description: null, source_url: "https://x.example.com/r" }),
      }),
    );

    renderWithQuery(<JobDetail jobId="job-1" />);

    expect(await screen.findByRole("button", { name: /try the link again/i })).toBeInTheDocument();
  });

  it("loads the preserved original only when asked", async () => {
    const fetchMock = routes({
      job: job(),
      source: {
        job_id: "job-1",
        import_method: "PASTED_DESCRIPTION",
        source_url: null,
        original_description: "The posting exactly as it arrived.",
        raw_content: null,
        extracted_text: null,
        imports: [{ id: "i1", imported_at: "2026-07-27T00:00:00Z", redirect_chain: [] }],
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobDetail jobId="job-1" />);
    await screen.findByRole("heading", { name: "Senior Backend Engineer" });

    // Raw job-page HTML is large and almost never looked at.
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/source"))).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: /show the original/i }));

    expect(await screen.findByText("The posting exactly as it arrived.")).toBeInTheDocument();
  });

  it("archives a job", async () => {
    const fetchMock = routes({ job: job() });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<JobDetail jobId="job-1" />);
    await screen.findByRole("heading", { name: "Senior Backend Engineer" });

    await userEvent.click(screen.getByRole("button", { name: /^archive$/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/archive"))).toBe(true);
    });
  });

  it("offers to bring an archived job back", async () => {
    vi.stubGlobal("fetch", routes({ job: job({ archived_at: "2026-07-27T00:00:00Z" }) }));

    renderWithQuery(<JobDetail jobId="job-1" />);

    expect(await screen.findByRole("button", { name: /bring back/i })).toBeInTheDocument();
  });

  it("says what archiving and deleting each do", async () => {
    vi.stubGlobal("fetch", routes({ job: job() }));

    renderWithQuery(<JobDetail jobId="job-1" />);

    expect(await screen.findByText(/Archiving keeps the job and its posting/)).toBeInTheDocument();
  });
});
