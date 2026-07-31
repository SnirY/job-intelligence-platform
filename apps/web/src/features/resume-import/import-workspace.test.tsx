import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportWorkspace } from "@/features/resume-import/import-workspace";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWorkspace(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function ok(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

function document(overrides: Record<string, unknown> = {}) {
  return {
    id: "doc-1",
    original_filename: "resume.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    status: "PARSED",
    extraction_error: null,
    created_at: "2026-07-26T00:00:00Z",
    ...overrides,
  };
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    status: "COMPLETED",
    step: "COMPLETED",
    attempts: 1,
    max_attempts: 5,
    error_code: null,
    error_message: null,
    is_retriable: false,
    ...overrides,
  };
}

function extractionItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    candidate_type: "SKILL",
    parent_item_id: null,
    display_order: 0,
    payload: { name: "Python" },
    edited_payload: null,
    confidence: 95,
    source_text: null,
    decision: "PENDING",
    target_entity_type: null,
    target_entity_id: null,
    ...overrides,
  };
}

function extraction(items: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    id: "extraction-1",
    version: 1,
    prompt_version: "resume_parser_v1",
    model: "test-model",
    provider: "fake",
    warnings: [],
    confirmed_at: null,
    items,
    ...overrides,
  };
}

/**
 * Routes fetches by URL.
 *
 * The workspace makes two calls — the import list and the review — so a single
 * canned response would answer the wrong one.
 */
function routes(review: unknown, imports: unknown[] = [{ document: document(), job: job() }]) {
  // Typed with the init argument so `mock.calls[n][1].body` is reachable —
  // several tests assert on the request body they sent.
  return vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    if (url.includes("/extraction")) return ok(review);
    if (url.includes("/imports")) return ok(imports);
    return ok(null);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("upload", () => {
  it("offers an upload control before anything has been imported", async () => {
    vi.stubGlobal("fetch", routes(null, []));

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByRole("button", { name: /choose a file/i })).toBeInTheDocument();
  });

  it("states which formats are accepted", async () => {
    vi.stubGlobal("fetch", routes(null, []));

    renderWorkspace(<ImportWorkspace />);

    // Only the formats that work end to end. Naming a third here would promise
    // something the pipeline cannot deliver.
    expect(await screen.findByText(/PDF or DOCX/)).toBeInTheDocument();
  });

  it("reports a load failure rather than showing an empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/Could not load your imports/)).toBeInTheDocument();
  });
});

describe("processing", () => {
  it("shows progress while the document is being read", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "EXTRACTING" }),
        job: job({ status: "RUNNING", step: "EXTRACTING" }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/Reading your document/)).toBeInTheDocument();
  });

  it("reassures the user their file survived a failure", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "FAILED" }),
        job: job({
          status: "FAILED",
          step: "PARSING",
          error_code: "PROVIDER_ERROR",
          error_message: "The AI provider could not be reached.",
          is_retriable: true,
        }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    // GOAL.md: failures must not destroy user work — and the user has to be
    // told that, or they will re-upload a file that is already stored.
    expect(await screen.findByText(/Your file is safe/)).toBeInTheDocument();
    expect(screen.getByText(/could not be reached/)).toBeInTheDocument();
  });

  it("offers a retry when trying again could work", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "FAILED" }),
        job: job({ status: "FAILED", error_message: "Temporary failure", is_retriable: true }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("withholds the retry when trying again cannot help", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "FAILED" }),
        job: job({
          status: "FAILED",
          error_code: "CONTENT_UNAVAILABLE",
          error_message: "No readable text was found in this document.",
          is_retriable: false,
        }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    // A scan will not gain a text layer on a second attempt, and a button that
    // always fails reads as a broken product.
    expect(await screen.findByText(/will not help/)).toBeInTheDocument();
    expect(screen.getByText(/Upload a different file/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("does not send the user hunting for another file when the server is at fault", async () => {
    // DEV-021. Found by unsetting the AI key and reading the screen: the
    // advice was "upload a different file instead", which is true for a
    // document with no text layer and useless for a server with no API key.
    // Nothing the user does to their resume reaches this problem.
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "FAILED" }),
        job: job({
          status: "FAILED",
          error_code: "PROVIDER_ERROR",
          error_message: "AI is not configured on this server.",
          is_retriable: false,
        }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/attention on the server/)).toBeInTheDocument();
    expect(screen.queryByText(/Upload a different file/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("shows no proposals at all when AI is unavailable", async () => {
    // The rule the whole product rests on: never return fake intelligence when
    // AI is unavailable. An empty-but-plausible review screen would be worse
    // than an error, because it looks like a result.
    vi.stubGlobal(
      "fetch",
      routes({
        document: document({ status: "FAILED" }),
        job: job({
          status: "FAILED",
          error_code: "PROVIDER_ERROR",
          error_message: "AI is not configured on this server.",
          is_retriable: false,
        }),
        extraction: null,
      }),
    );

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText(/AI is not configured/);

    expect(screen.queryByText(/Review what we found/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add to my profile/i })).not.toBeInTheDocument();
  });
});

describe("review", () => {
  const review = {
    document: document(),
    job: job(),
    extraction: extraction([
      extractionItem({ id: "skill-1", payload: { name: "Python" }, confidence: 95 }),
      extractionItem({
        id: "exp-1",
        candidate_type: "EXPERIENCE",
        payload: { company: "Verdant Logistics", title: "Backend Engineer" },
        confidence: 90,
      }),
      extractionItem({
        id: "ach-1",
        candidate_type: "EXPERIENCE_ACHIEVEMENT",
        parent_item_id: "exp-1",
        payload: { text: "Built the shipment tracker." },
        confidence: 85,
      }),
    ]),
  };

  it("presents candidates as proposals rather than profile data", async () => {
    vi.stubGlobal("fetch", routes(review));

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/not part of your profile yet/)).toBeInTheDocument();
  });

  it("offers accept, edit, and ignore on every candidate", async () => {
    vi.stubGlobal("fetch", routes(review));

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText("Python");

    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Ignore" })).toHaveLength(3);
  });

  it("nests an achievement under its role", async () => {
    vi.stubGlobal("fetch", routes(review));

    renderWorkspace(<ImportWorkspace />);

    // Achievements have no section of their own: a bullet is only meaningful
    // under the job it belongs to, and it cannot be approved without one.
    expect(await screen.findByText("Built the shipment tracker.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Achievements" })).not.toBeInTheDocument();
  });

  it("shows how sure the parser was", async () => {
    vi.stubGlobal("fetch", routes(review));

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText("95% sure")).toBeInTheDocument();
  });

  it("warns about a candidate that could not be verified", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        ...review,
        extraction: extraction([
          extractionItem({
            payload: { name: "Python", flags: ["UNSUPPORTED_NUMBERS"] },
            confidence: 40,
          }),
        ]),
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/number your document does not/)).toBeInTheDocument();
  });

  it("shows the quoted source so the user can check it", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        ...review,
        extraction: extraction([extractionItem({ source_text: "Python, FastAPI, PostgreSQL" })]),
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/Python, FastAPI, PostgreSQL/)).toBeInTheDocument();
  });

  it("surfaces validation warnings", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        ...review,
        extraction: extraction([extractionItem()], {
          warnings: ["Verdant Logistics: the end date could not be read."],
        }),
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/the end date could not be read/)).toBeInTheDocument();
  });

  it("marks a candidate the user already has", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        ...review,
        extraction: extraction([
          extractionItem({ target_entity_type: "user_skill", target_entity_id: "skill-uuid" }),
        ]),
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/Already on your profile/)).toBeInTheDocument();
  });

  it("sends one decision per candidate on confirm", async () => {
    const fetchMock = routes(review);
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText("Python");

    await userEvent.click(screen.getByRole("button", { name: /add to my profile/i }));

    await waitFor(() => {
      const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/confirm"));
      expect(confirmCall).toBeDefined();
      const body = JSON.parse(String(confirmCall?.[1]?.body));
      expect(body.decisions).toHaveLength(3);
    });
  });

  it("sends IGNORE for a candidate the user rejected", async () => {
    const fetchMock = routes({
      ...review,
      extraction: extraction([extractionItem({ id: "skill-1" })]),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText("Python");

    await userEvent.click(screen.getByRole("button", { name: "Ignore" }));
    await userEvent.click(screen.getByRole("button", { name: /add to my profile/i }));

    await waitFor(() => {
      const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/confirm"));
      const body = JSON.parse(String(confirmCall?.[1]?.body));
      expect(body.decisions[0]).toEqual({ item_id: "skill-1", action: "IGNORE" });
    });
  });

  it("sends the edited values when the user changes a candidate", async () => {
    const fetchMock = routes({
      ...review,
      extraction: extraction([
        extractionItem({
          id: "exp-1",
          candidate_type: "EXPERIENCE",
          payload: { company: "Verdant Logistics", title: "Backend Engineer" },
        }),
      ]),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText(/Backend Engineer/);

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const titleField = await screen.findByLabelText("title");
    await userEvent.clear(titleField);
    await userEvent.type(titleField, "Senior Backend Engineer");

    await userEvent.click(screen.getByRole("button", { name: /add to my profile/i }));

    await waitFor(() => {
      const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/confirm"));
      const body = JSON.parse(String(confirmCall?.[1]?.body));
      expect(body.decisions[0].action).toBe("EDIT");
      expect(body.decisions[0].payload.title).toBe("Senior Backend Engineer");
    });
  });

  it("reports a confirmation failure without claiming anything was saved", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      void init;
      if (url.includes("/confirm")) throw new TypeError("Failed to fetch");
      if (url.includes("/extraction")) return ok(review);
      return ok([{ document: document(), job: job() }]);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace(<ImportWorkspace />);
    await screen.findByText("Python");

    await userEvent.click(screen.getByRole("button", { name: /add to my profile/i }));

    expect(await screen.findByText(/Nothing was changed/)).toBeInTheDocument();
  });

  it("summarises the outcome once everything has been decided", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        ...review,
        extraction: extraction([
          extractionItem({ decision: "ACCEPTED" }),
          extractionItem({ id: "item-2", decision: "IGNORED" }),
        ]),
      }),
    );

    renderWorkspace(<ImportWorkspace />);

    expect(await screen.findByText(/Import complete/)).toBeInTheDocument();
    expect(screen.getByText(/1 item was added to your profile/)).toBeInTheDocument();
  });
});
