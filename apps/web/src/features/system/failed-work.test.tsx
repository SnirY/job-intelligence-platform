import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FailedWork } from "@/features/system/failed-work";

/**
 * The one operational panel in the product, and the two things it must not do.
 *
 * It must not appear when nothing has failed — a panel headed "failures" that
 * is empty every day is a panel you stop reading on the day it is not.
 *
 * And a row that is over must not look like a row you can act on. Offering
 * "Try again" on a permanent failure teaches the reader that the button does
 * nothing, which is worse than the failure.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function failure(overrides: Record<string, unknown> = {}) {
  return {
    id: "pj-1",
    kind: "RESUME_IMPORT",
    status: "FAILED",
    step: "PARSING",
    entity_type: "source_document",
    entity_id: "doc-1",
    entity_label: "resume.pdf",
    attempts: 1,
    max_attempts: 5,
    error_code: "PROVIDER_ERROR",
    error_message: "The model did not answer.",
    is_retriable: true,
    can_be_retried: true,
    is_dead: false,
    finished_at: "2026-08-24T09:00:00Z",
    ...overrides,
  };
}

function server(rows: unknown[]) {
  const calls: Array<{ url: string; method: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method ?? "GET" });
      return { ok: true, status: 200, json: async () => ({ data: rows }) };
    }),
  );
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

describe("when nothing has failed", () => {
  it("renders nothing at all", async () => {
    server([]);
    const { container } = renderWithQuery(<FailedWork />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("a failure that can be tried again", () => {
  it("names the thing rather than its id", async () => {
    server([failure()]);
    renderWithQuery(<FailedWork />);

    expect(await screen.findByText("resume.pdf")).toBeInTheDocument();
    expect(screen.queryByText("doc-1")).not.toBeInTheDocument();
  });

  it("says why it stopped, and offers the retry", async () => {
    server([failure()]);
    renderWithQuery(<FailedWork />);

    expect(await screen.findByText(/did not answer/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("posts to the retry endpoint for that job", async () => {
    const calls = server([failure()]);
    renderWithQuery(<FailedWork />);

    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "POST" && c.url.includes("/processing-jobs/pj-1/retry")),
      ).toBe(true);
    });
  });
});

describe("a failure that is over", () => {
  it("offers no button", async () => {
    /** The distinction the panel exists to draw. */
    server([failure({ can_be_retried: false, is_dead: true, is_retriable: false })]);
    renderWithQuery(<FailedWork />);

    await screen.findByText("resume.pdf");
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("says so in words rather than by the button's absence", async () => {
    server([failure({ can_be_retried: false, is_dead: true, is_retriable: false })]);
    renderWithQuery(<FailedWork />);

    expect(await screen.findByText(/trying again will not help/i)).toBeInTheDocument();
  });
});

describe("what the work was", () => {
  it("is described in the reader's terms, not the queue's", async () => {
    server([failure({ kind: "JOB_ANALYSIS", entity_label: null })]);
    renderWithQuery(<FailedWork />);

    expect(await screen.findByText("Reading a posting")).toBeInTheDocument();
    expect(screen.queryByText("JOB_ANALYSIS")).not.toBeInTheDocument();
  });

  it("still lists a kind nobody has written a name for", async () => {
    /** A job kind added later must appear as an unlabelled row rather than
     * breaking the page that reports trouble. */
    server([failure({ kind: "SOMETHING_NEW", entity_label: null })]);
    renderWithQuery(<FailedWork />);

    expect(await screen.findByText("Background work")).toBeInTheDocument();
  });
});
