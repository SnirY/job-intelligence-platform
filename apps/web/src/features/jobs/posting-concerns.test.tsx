import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PostingConcerns } from "@/features/jobs/posting-concerns";

/**
 * What the screen may say about a posting, and what it may not.
 *
 * Two rules are under test and both are about restraint. A concern must never
 * read as part of the match — a role can fit well and still be worth a second
 * look, and folding either reading into the other leaves nobody able to tell
 * which a low number meant. And an empty result means *no rule fired*, which is
 * not the same as "this posting is trustworthy": a green tick there would
 * assert exactly the thing the rules cannot support.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

const PAYMENT = {
  type: "PAYMENT_REQUESTED",
  confidence: "NEAR_CERTAIN",
  summary: "This posting asks you to pay something to be hired.",
  evidence: "…There is a one-time training fee of $250…",
};

const THIN = {
  type: "THIN_DESCRIPTION",
  confidence: "OBSERVED",
  summary: "There is very little text in this posting.",
  evidence: null,
};

function server(concerns: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        data: { job_id: "job-1", rules_version: "1.0.0", concerns },
      }),
    })),
  );
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

describe("when no rule fired", () => {
  it("renders nothing at all", async () => {
    server([]);
    const { container } = renderWithQuery(<PostingConcerns jobId="job-1" />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("never claims the posting is fine", async () => {
    /** The absence that matters. No rule firing is a fact about our rules, not
     * a finding about the world. */
    server([]);
    renderWithQuery(<PostingConcerns jobId="job-1" />);

    await waitFor(() => {
      expect(screen.queryByText(/no concerns/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/looks legitimate/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/verified/i)).not.toBeInTheDocument();
    });
  });
});

describe("when something was noticed", () => {
  it("states the observation and quotes the posting", async () => {
    server([PAYMENT]);
    renderWithQuery(<PostingConcerns jobId="job-1" />);

    expect(await screen.findByText(/asks you to pay something/i)).toBeInTheDocument();
    expect(screen.getByText(/one-time training fee/i)).toBeInTheDocument();
  });

  it("says outright that this does not affect the match", async () => {
    /** The rule the whole slice turns on, said on the screen rather than only
     * kept in the engine. */
    server([PAYMENT]);
    renderWithQuery(<PostingConcerns jobId="job-1" />);

    expect(await screen.findByText(/does not affect your match/i)).toBeInTheDocument();
  });

  it("carries the seriousness in words, not only in colour", async () => {
    /** Invariant 3. Three levels is exactly the kind of distinction a palette
     * would otherwise be asked to carry alone. */
    server([PAYMENT, THIN]);
    renderWithQuery(<PostingConcerns jobId="job-1" />);

    expect(await screen.findByText("Serious")).toBeInTheDocument();
    expect(screen.getByText("Worth knowing")).toBeInTheDocument();
  });

  it("shows no quote for a rule that measured rather than read", async () => {
    server([THIN]);
    const { container } = renderWithQuery(<PostingConcerns jobId="job-1" />);

    await screen.findByText(/very little text/i);
    expect(container.querySelector("blockquote")).toBeNull();
  });

  it("shows no score, rating or number anywhere", async () => {
    /**
     * A number is what could later be averaged into the match. If this test has
     * to change, the change is the thing to argue about.
     */
    server([PAYMENT, THIN]);
    const { container } = renderWithQuery(<PostingConcerns jobId="job-1" />);

    await screen.findByText(/asks you to pay something/i);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\b\d+\s*(?:\/|out of)\s*\d+\b/);
    expect(text).not.toMatch(/risk score|legitimacy score|rating/i);
  });

  it("does not accuse the employer of anything", async () => {
    server([THIN]);
    const { container } = renderWithQuery(<PostingConcerns jobId="job-1" />);

    await screen.findByText(/very little text/i);
    expect(container.textContent ?? "").not.toMatch(/scam|fraud|fake/i);
  });
});
