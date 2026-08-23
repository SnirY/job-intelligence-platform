import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Discovery } from "@/features/discovery/discovery";

/**
 * The discovery screen, and the line it is built around.
 *
 * A scan produces **candidates**. Only a person turns one into a job, and the
 * screen has to make that obvious rather than merely true. So the assertions
 * here are mostly about what is absent: no score beside a candidate, no path
 * into the job library that a click did not open.
 *
 * Per `AGENTS.md` these assert sentences and roles, never a class.
 */

const push = vi.fn();

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const POSTING = {
  id: "posting-1",
  provider: "greenhouse",
  board: "verdant",
  title: "Senior Backend Engineer",
  url: "https://boards.greenhouse.io/verdant/jobs/1",
  company: "Verdant Logistics",
  location: "Lisbon, Portugal",
  posted_at: "2026-08-01T09:00:00Z",
  first_seen_at: "2026-08-20T09:00:00Z",
  last_seen_at: "2026-08-23T09:00:00Z",
  has_description: true,
};

const BOARD = {
  id: "board-1",
  provider: "greenhouse",
  token: "verdant",
  label: "Verdant Logistics",
  paused_at: null,
  last_scanned_at: "2026-08-23T09:00:00Z",
  last_error: null,
  created_at: "2026-08-01T09:00:00Z",
};

function server(
  options: {
    boards?: unknown[];
    postings?: unknown[];
    scanBoards?: number;
    promoteStatus?: number;
  } = {},
) {
  const { boards = [BOARD], postings = [POSTING], scanBoards = 1, promoteStatus = 201 } = options;

  const calls: Array<{ url: string; method: string }> = [];

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(url);
    calls.push({ url: path, method });

    const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => ({ data }) });

    if (path.includes("/discovery/providers")) return ok(["greenhouse", "ashby", "lever"]);
    if (path.includes("/discovery/scan")) return ok({ boards: scanBoards });

    if (path.includes("/promote")) {
      if (promoteStatus === 409) {
        return {
          ok: false,
          status: 409,
          json: async () => ({
            // `code` is not optional: `isErrorResponse` requires it, and
            // without it the client raises a transport error instead of an
            // `ApiError` and the 409 branch never runs.
            error: {
              code: "CONFLICT",
              message: "You have already saved this job.",
              details: { existing_job_id: "job-9", existing_title: "Senior Backend Engineer" },
            },
          }),
        };
      }
      return { ok: true, status: 201, json: async () => ({ data: { job_id: "job-7" } }) };
    }

    if (path.includes("/dismiss")) return ok(POSTING);
    if (path.includes("/discovery/boards")) return ok(boards);

    if (path.includes("/discovery/postings")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          data: postings,
          meta: { page: 1, page_size: 25, total: postings.length, total_pages: 1 },
        }),
      };
    }

    return ok(null);
  });

  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("what a candidate is allowed to say", () => {
  it("shows the posting without judging it", async () => {
    server();
    renderWithQuery(<Discovery />);

    expect(await screen.findByText("Senior Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Verdant Logistics · Lisbon, Portugal/)).toBeInTheDocument();
  });

  it("shows no score, match or alignment beside it", async () => {
    /**
     * The absence that matters. Those are readings from the analysis pipeline,
     * which a posting reaches only after a person promotes it — a figure here
     * would mean the system had judged something nobody had chosen.
     */
    server();
    renderWithQuery(<Discovery />);
    await screen.findByText("Senior Backend Engineer");

    expect(screen.queryByText(/alignment/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/match/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });

  it("says when the board carried no description", async () => {
    server({ postings: [{ ...POSTING, has_description: false }] });
    renderWithQuery(<Discovery />);

    expect(await screen.findByText(/no description on the board/i)).toBeInTheDocument();
  });
});

describe("the decision", () => {
  it("adds to jobs only when asked, and goes to the job", async () => {
    const calls = server();
    renderWithQuery(<Discovery />);
    await screen.findByText("Senior Backend Engineer");

    // Nothing has been promoted merely by rendering the list.
    expect(calls.some((c) => c.url.includes("/promote"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: /add to jobs/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/jobs/job-7"));
  });

  it("offers a way through when the job is already saved", async () => {
    /** A board listing something pasted last week is a normal outcome here,
     * so it gets an answer rather than a red failure. */
    server({ promoteStatus: 409 });
    renderWithQuery(<Discovery />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.click(screen.getByRole("button", { name: /add to jobs/i }));

    expect(await screen.findByText(/already saved this job/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add anyway/i })).toBeInTheDocument();
  });

  it("dismisses a posting", async () => {
    const calls = server();
    renderWithQuery(<Discovery />);
    await screen.findByText("Senior Backend Engineer");

    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.url.includes("/dismiss"))).toBe(true);
    });
  });
});

describe("states with nothing in them", () => {
  it("tells a reader with no boards what to do", async () => {
    server({ boards: [], postings: [] });
    renderWithQuery(<Discovery />);

    expect(await screen.findByText(/no boards yet/i)).toBeInTheDocument();
  });

  it("does not imply a scan is running when there is nothing to scan", async () => {
    server({ boards: [], postings: [], scanBoards: 0 });
    renderWithQuery(<Discovery />);
    await screen.findByText(/no boards yet/i);

    await userEvent.click(screen.getByRole("button", { name: /scan now/i }));

    expect(await screen.findByText(/nothing to scan yet/i)).toBeInTheDocument();
  });

  it("says the list is empty rather than showing a blank region", async () => {
    server({ postings: [] });
    renderWithQuery(<Discovery />);

    expect(await screen.findByText(/nothing waiting/i)).toBeInTheDocument();
  });
});

describe("a board that could not be read", () => {
  it("names the board rather than folding it into a count", async () => {
    /** "We read four of your five" is only actionable if the screen can name
     * the fifth. */
    server({ boards: [{ ...BOARD, last_error: "The board returned 404." }] });
    renderWithQuery(<Discovery />);

    const row = (await screen.findByText("Verdant Logistics")).closest("div");
    expect(within(row as HTMLElement).getByText(/returned 404/)).toBeInTheDocument();
  });

  it("shows when a board was last read when it worked", async () => {
    server();
    renderWithQuery(<Discovery />);

    expect(await screen.findByText(/last read/i)).toBeInTheDocument();
  });
});
