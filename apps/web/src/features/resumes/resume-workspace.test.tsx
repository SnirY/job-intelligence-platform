import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResumeWorkspace } from "@/features/resumes/resume-workspace";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function resume(overrides: Record<string, unknown> = {}) {
  return {
    id: "resume-1",
    title: "Backend Engineer",
    family: "BASE",
    job_id: null,
    parent_resume_id: null,
    description: null,
    archived_at: null,
    created_at: "2026-07-29T00:00:00Z",
    updated_at: "2026-07-29T00:00:00Z",
    ...overrides,
  };
}

function version(overrides: Record<string, unknown> = {}) {
  return {
    id: "version-1",
    resume_id: "resume-1",
    version: 1,
    parent_version_id: null,
    status: "DRAFT",
    label: "First draft",
    used_at: null,
    created_at: "2026-07-29T00:00:00Z",
    updated_at: "2026-07-29T00:00:00Z",
    ...overrides,
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...version(),
    is_editable: true,
    sections: [
      {
        id: "section-1",
        kind: "EXPERIENCE",
        title: null,
        display_order: 0,
        items: [
          {
            id: "item-1",
            text: "Built the routing service.",
            heading: "Backend Engineer, Verdant",
            source_type: "ACHIEVEMENT",
            source_entity_id: "ach-1",
            display_order: 0,
          },
        ],
      },
    ],
    ...overrides,
  };
}

/** Dispatches on the URL, because the editor reads three endpoints. */
function routes(overrides: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    resumes: [resume()],
    versions: [version()],
    detail: detail(),
    ...overrides,
  };

  return vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    const path = String(url);
    let data = table.resumes;
    if (path.includes("/versions")) data = table.versions;
    if (path.includes("/resume-versions/")) data = table.detail;

    return {
      ok: true,
      status: 200,
      text: async () => "<html><body>rendered</body></html>",
      json: async () => ({ data }),
    };
  });
}

afterEach(() => vi.unstubAllGlobals());

// --- getting started ------------------------------------------------------------

describe("an empty account", () => {
  it("asks for a base resume rather than showing an empty editor", async () => {
    vi.stubGlobal("fetch", routes({ resumes: [] }));

    renderWithQuery(<ResumeWorkspace />);

    expect(await screen.findByText(/Start with a base resume/)).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderWithQuery(<ResumeWorkspace />);

    expect(await screen.findByText(/Could not load your resumes/)).toBeInTheDocument();
  });
});

// --- editing --------------------------------------------------------------------

describe("editing a version", () => {
  it("loads the version's content into the editor", async () => {
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);

    const experience = await screen.findByLabelText("Experience");
    expect(experience).toHaveValue("# Backend Engineer, Verdant\nBuilt the routing service.");
  });

  it("saves the whole version when asked", async () => {
    const fetchMock = routes();
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.some(
        ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
      );
      expect(put).toBe(true);
    });
  });
});

// --- immutability ---------------------------------------------------------------

describe("a version that has been sent", () => {
  it("explains why it cannot be edited rather than failing on save", async () => {
    // The rule the screen is built around. Letting someone type into a frozen
    // document and then rejecting the save would be a worse way to say this.
    vi.stubGlobal(
      "fetch",
      routes({
        versions: [version({ status: "USED" })],
        detail: detail({ status: "USED", is_editable: false }),
      }),
    );

    renderWithQuery(<ResumeWorkspace />);

    expect(await screen.findByText(/its\s+content is fixed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Experience")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("offers no further status transitions", async () => {
    vi.stubGlobal(
      "fetch",
      routes({
        versions: [version({ status: "USED" })],
        detail: detail({ status: "USED", is_editable: false }),
      }),
    );

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");

    expect(screen.queryByRole("button", { name: /mark as sent/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /move to/i })).not.toBeInTheDocument();
  });

  it("offers only the transitions the server allows", async () => {
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");

    // A draft may go to review or straight to approved, but never to sent.
    expect(screen.getByRole("button", { name: /move to in review/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /move to approved/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as sent/i })).not.toBeInTheDocument();
  });
});

// --- printing -------------------------------------------------------------------

describe("printing", () => {
  it("writes the rendered document into the tab it opened", async () => {
    // The tab has to be opened on the click itself or the browser blocks it,
    // and it has to be opened without `noopener` or the handle comes back null
    // and nothing is ever written to it.
    const write = vi.fn();
    const open = vi.fn((_url?: string, _target?: string, features?: string) => {
      // `noopener` in the features string severs the handle and makes
      // window.open return null, so asserting it is absent is asserting the
      // print flow can work at all.
      expect(features).toBeUndefined();
      return { document: { write, close: vi.fn() } };
    });
    vi.stubGlobal("fetch", routes());
    vi.stubGlobal("open", open);

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");

    await userEvent.click(screen.getByRole("button", { name: /preview \/ print/i }));

    await waitFor(() => expect(write).toHaveBeenCalledWith("<html><body>rendered</body></html>"));
    expect(open).toHaveBeenCalled();
  });

  it("fetches the rendered page with the session token rather than linking to it", async () => {
    // A plain link would reach the API without an Authorization header — the
    // same check that stops one user downloading another's resume.
    const fetchMock = routes();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal(
      "open",
      vi.fn(() => ({ document: { write: vi.fn(), close: vi.fn() } })),
    );

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");

    await userEvent.click(screen.getByRole("button", { name: /preview \/ print/i }));

    await waitFor(() => {
      const rendered = fetchMock.mock.calls.find(([url]) => String(url).includes("/render"));
      expect(rendered).toBeDefined();
      const headers = (rendered?.[1] as RequestInit | undefined)?.headers as
        Record<string, string> | undefined;
      expect(headers?.Authorization).toBe("Bearer token");
    });
  });
});
