import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoverLetterPanel } from "@/features/resumes/cover-letter";

/**
 * What the cover letter panel may show, and the two rules it exists to keep.
 *
 * A blocked claim is shown **and the letter is shown with it**. `docs/06` wants
 * the system to ask for a missing metric, not to refuse the document — the user
 * may know the figure is real. Hiding the draft would be the system deciding it
 * knows better than the person whose career it is.
 *
 * And a human edit is not re-validated, so the screen must stop presenting
 * claims that describe words no longer on it.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

const JOB = { id: "job-1", status: "ANALYZED" };

const BLOCKED_CLAIM = {
  text: "I reduced reconciliation errors by 40%.",
  status: "BLOCKED",
  explanation: "The figure 40% does not appear anywhere in your profile.",
  confidence: 90,
};

function letter(overrides: Record<string, unknown> = {}) {
  return {
    id: "letter-1",
    job_id: "job-1",
    status: "DRAFTED",
    angle: null,
    body: "I have built REST services in Python and FastAPI.",
    angle_warning: null,
    error: null,
    edited_at: null,
    approved_at: null,
    created_at: "2026-08-23T09:00:00Z",
    claims: [],
    ...overrides,
  };
}

function server(data: unknown) {
  const calls: Array<{ url: string; method: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method ?? "GET" });
      return { ok: true, status: 200, json: async () => ({ data }) };
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

describe("before there is a letter", () => {
  it("offers to write one, and does not write one by itself", async () => {
    const calls = server(null);
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByRole("button", { name: /write a draft/i })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("lets the angle be left blank", async () => {
    server(null);
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    const field = await screen.findByLabelText(/what should it argue/i);
    expect(field).toHaveAttribute("placeholder", expect.stringMatching(/leave blank/i));
  });
});

describe("a draft with a blocked claim", () => {
  it("shows the problem", async () => {
    server(letter({ claims: [BLOCKED_CLAIM] }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/says something your profile does not/i)).toBeInTheDocument();
    expect(screen.getByText(/does not appear anywhere in your profile/i)).toBeInTheDocument();
  });

  it("still shows the letter, and still lets it be approved", async () => {
    /**
     * The rule worth protecting. `docs/06` asks for a missing metric rather
     * than refusing the document — the user may know the figure is real.
     */
    server(letter({ claims: [BLOCKED_CLAIM] }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/built REST services in Python/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /looks right/i })).toBeInTheDocument();
  });

  it("says what to do about it", async () => {
    server(letter({ claims: [BLOCKED_CLAIM] }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/add them to your profile/i)).toBeInTheDocument();
  });
});

describe("after a person has edited it", () => {
  it("stops presenting checks that describe the old words", async () => {
    server(letter({ status: "EDITED", claims: [BLOCKED_CLAIM] }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/no longer describe what is on screen/i)).toBeInTheDocument();
    expect(screen.queryByText(/says something your profile does not/i)).not.toBeInTheDocument();
  });
});

describe("the angle the model could not take", () => {
  it("is shown rather than logged", async () => {
    server(letter({ angle_warning: "Your profile has no management experience to argue from." }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/no management experience/i)).toBeInTheDocument();
  });
});

describe("a draft that failed", () => {
  it("says why, and looks like a failure", async () => {
    server(letter({ status: "FAILED", body: null, error: "The model did not answer." }));
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    expect(await screen.findByText(/did not answer/i)).toBeInTheDocument();
  });
});

describe("editing", () => {
  it("sends the text a person wrote", async () => {
    const calls = server(letter());
    renderWithQuery(<CoverLetterPanel job={JOB as never} />);

    await userEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "PATCH" && c.url.includes("/cover-letters/letter-1")),
      ).toBe(true);
    });
  });
});
