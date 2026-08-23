import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobLiveness } from "@/features/jobs/job-liveness";

/**
 * What the screen is allowed to say about a posting it has or has not checked.
 *
 * The test that matters most here is the unchecked one, and it asserts an
 * absence. Invariant 14: an absent date is not an unknown date. Both timestamps
 * are null until a check concludes something, and a check that could not reach
 * the server writes nothing — so null means nobody has looked, and the screen
 * must not turn that into a claim in either direction.
 *
 * Nothing here asserts a colour. Per `AGENTS.md` the suite asserts sentences,
 * and the sentence is the part that would be wrong.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

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
  source_url: "https://jobs.example.com/role/12",
  import_method: "URL",
  status: "ANALYZED",
  notes: null,
  salary_text: null,
  fetch_error: null,
  archived_at: null,
  last_seen_alive_at: null,
  closed_detected_at: null,
  created_at: "2026-07-27T00:00:00Z",
  updated_at: "2026-07-27T00:00:00Z",
} as const;

type JobShape = typeof JOB;

function server(job: Record<string, unknown>, options: { checkFails?: boolean } = {}) {
  const calls: Array<{ url: string; method: string }> = [];

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url: String(url), method });

    if (method === "POST" && options.checkFails) {
      return { ok: false, status: 503, json: async () => ({ error: { message: "no" } }) };
    }

    return { ok: true, status: 200, json: async () => ({ data: job }) };
  });

  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function job(overrides: Partial<Record<keyof JobShape, unknown>> = {}) {
  return { ...JOB, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a link nobody has checked", () => {
  it("says so, and claims nothing in either direction", async () => {
    server(job());
    renderWithQuery(<JobLiveness job={job() as never} />);

    expect(await screen.findByText(/has not been checked/i)).toBeInTheDocument();

    // The two claims a null timestamp must never become. Invariant 14: absence
    // of a value is a fact about the record, not a statement about the world.
    expect(screen.queryByText(/returned nothing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/the link answered/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/filled or withdrawn/i)).not.toBeInTheDocument();
  });

  it("offers the check as an unqualified first look", async () => {
    server(job());
    renderWithQuery(<JobLiveness job={job() as never} />);

    expect(await screen.findByRole("button", { name: /^check$/i })).toBeInTheDocument();
  });
});

describe("a link that answered", () => {
  it("reports what the link did and when, not whether the role is open", async () => {
    const alive = job({ last_seen_alive_at: "2026-08-23T12:00:00Z" });
    server(alive);
    renderWithQuery(<JobLiveness job={alive as never} />);

    // The date is rendered through the reader's own locale, so the assertion
    // is that one is there rather than which order its parts come in.
    expect(await screen.findByText(/the link answered on/i)).toHaveTextContent(/2026/);
    expect(screen.getByRole("button", { name: /check again/i })).toBeInTheDocument();
  });
});

describe("a link that returned nothing", () => {
  it("dates the observation and says the job survives it", async () => {
    const closed = job({ closed_detected_at: "2026-08-23T12:00:00Z" });
    server(closed);
    renderWithQuery(<JobLiveness job={closed as never} />);

    expect(await screen.findByText(/the link returned nothing on/i)).toBeInTheDocument();

    // Invariant 8: a failure never destroys work, and the screen says so. A
    // closed posting must not read as though the job record is going with it.
    expect(screen.getByText(/stay exactly where they are/i)).toBeInTheDocument();
  });
});

describe("asking for a check", () => {
  it("posts to the job's own check endpoint", async () => {
    const calls = server(job());
    renderWithQuery(<JobLiveness job={job() as never} />);

    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }));

    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "POST" && c.url.includes("/jobs/job-1/liveness-check")),
      ).toBe(true);
    });
  });

  it("says the check could not be started when the queue refuses it", async () => {
    server(job(), { checkFails: true });
    renderWithQuery(<JobLiveness job={job() as never} />);

    await userEvent.click(await screen.findByRole("button", { name: /^check$/i }));

    expect(await screen.findByText(/could not be started/i)).toBeInTheDocument();
    // And the absence still reads as an absence rather than a verdict.
    expect(screen.getByText(/has not been checked/i)).toBeInTheDocument();
  });
});

describe("a job with no link", () => {
  it("renders nothing at all", () => {
    const pasted = job({ source_url: null, import_method: "PASTED_DESCRIPTION" });
    server(pasted);
    const { container } = renderWithQuery(<JobLiveness job={pasted as never} />);

    expect(container).toBeEmptyDOMElement();
  });
});
