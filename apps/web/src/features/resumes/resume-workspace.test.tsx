import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

// --- a heading with nothing under it (DEV-044) ---------------------------------

describe("a heading the model cannot store", () => {
  it("refuses the save instead of dropping the line", async () => {
    /* DEV-044. `fromDraft` carries a heading until a bullet arrives to attach
       it to, so a trailing `#` line reached the end of the loop and vanished —
       under a "Saved." The field's own hint invites exactly this. */
    const fetchMock = routes();
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ResumeWorkspace />);
    const projects = await screen.findByLabelText("Projects");

    await userEvent.clear(projects);
    await userEvent.type(projects, "# Reduced API latency by 40%");

    expect(await screen.findByRole("alert")).toHaveTextContent(/no lines under it/i);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    // The point of the whole fix: nothing was sent, so nothing was lost.
    const put = fetchMock.mock.calls.some(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(put).toBe(false);
  });

  it("names the section and the heading, so the line can be found", async () => {
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);
    const projects = await screen.findByLabelText("Projects");

    await userEvent.clear(projects);
    await userEvent.type(projects, "# Football Match Prediction");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Projects");
    expect(alert).toHaveTextContent("Football Match Prediction");
  });

  it("clears as soon as a line is added under the heading", async () => {
    /* A refusal that outlives its cause teaches people to ignore refusals. */
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);
    const projects = await screen.findByLabelText("Projects");

    await userEvent.clear(projects);
    await userEvent.type(projects, "# Football Match Prediction");
    await screen.findByRole("alert");

    await userEvent.type(projects, "{enter}Built an end-to-end ML pipeline.");

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("leaves an ordinary heading with bullets alone", async () => {
    /* The normal case has to keep working: this is the shape `toDraft` writes
       back for every experience in the fixture. */
    const fetchMock = routes();
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ResumeWorkspace />);
    const projects = await screen.findByLabelText("Projects");

    await userEvent.clear(projects);
    await userEvent.type(projects, "# A role{enter}A bullet beneath it.");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    /* Not a disabled textarea any more. A disabled control leaves the tab order
       and several screen readers announce it as unavailable or skip it — so on
       the version somebody actually sent, the document itself became the one
       thing on the screen a keyboard could not reach.

       It is still readable, still selectable, and still labelled. What it is
       not is an input. */
    /* Queried as a textbox rather than by label: the frozen block keeps its
       accessible name, so `getByLabelText` still finds it — which is the
       point. What has gone is the editable control, not the label. */
    expect(screen.queryByRole("textbox", { name: "Experience" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Experience" })).toBeInTheDocument();
  });

  it("moves between versions with arrow keys, at one tab stop", async () => {
    /* A tablist rather than a row of buttons carrying `aria-current`, which
       announces "current page" — a claim about navigation on a control that
       navigates nowhere. The pattern's payoff is the tab order: a resume with
       nine versions costs one stop, not nine. */
    vi.stubGlobal(
      "fetch",
      routes({
        versions: [version({ id: "v1", version: 1 }), version({ id: "v2", version: 2 })],
        detail: detail(),
      }),
    );

    renderWithQuery(<ResumeWorkspace />);
    const tabs = await screen.findByRole("tablist", { name: "Versions of this resume" });
    const [first, second] = within(tabs).getAllByRole("tab");

    expect(first).toHaveAttribute("tabindex", "0");
    expect(second).toHaveAttribute("tabindex", "-1");

    (first as HTMLElement).focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(second).toHaveAttribute("aria-selected", "true");
  });

  it("keeps the sent document readable rather than only visible", async () => {
    // The record an application refers to. Somebody quoting it into an email
    // needs to be able to select it.
    vi.stubGlobal(
      "fetch",
      routes({
        versions: [version({ status: "USED" })],
        detail: detail({ status: "USED", is_editable: false }),
      }),
    );

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByText(/its\s+content is fixed/);

    const experience = screen.getByRole("region", { name: "Experience" });
    expect(experience).toBeInTheDocument();
    expect(within(experience).queryByRole("textbox")).not.toBeInTheDocument();
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

    await userEvent.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(write).toHaveBeenCalledWith("<html><body>rendered</body></html>"));
    expect(open).toHaveBeenCalled();
  });

  it("says so when the browser blocks the print window", async () => {
    /* The case that used to be a button doing nothing. `window.open` returns
       null when a browser refuses, and the old handler read `if (!tab) return`
       — so the click ran, reported nothing, and left somebody pressing a button
       that had already worked.

       It has an answer now only because the render is on this screen: the page
       is below, and printing from there is the same thing. */
    vi.stubGlobal("fetch", routes());
    vi.stubGlobal(
      "open",
      vi.fn(() => null),
    );

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");
    await userEvent.click(screen.getByRole("button", { name: "Print" }));

    expect(await screen.findByText(/browser blocked the print window/)).toBeInTheDocument();
    expect(await screen.findByTitle("The rendered resume")).toBeInTheDocument();
  });

  it("shows the page without leaving the screen", async () => {
    // A resume is a document. Not being able to see it while writing it is the
    // one thing an editor for a document has to fix.
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");
    await userEvent.click(screen.getByRole("button", { name: "Show the page" }));

    expect(await screen.findByTitle("The rendered resume")).toBeInTheDocument();
  });

  it("says the page is of the last save, not of what is typed", async () => {
    /* The render is of the saved version and the editor above may have moved
       since. Stated rather than left for somebody to discover by printing an
       old draft. */
    vi.stubGlobal("fetch", routes());

    renderWithQuery(<ResumeWorkspace />);
    await screen.findByLabelText("Experience");
    await userEvent.click(screen.getByRole("button", { name: "Show the page" }));

    expect(await screen.findByText(/last saved version/)).toBeInTheDocument();
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

    await userEvent.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => {
      const rendered = fetchMock.mock.calls.find(([url]) => String(url).includes("/render"));
      expect(rendered).toBeDefined();
      const headers = (rendered?.[1] as RequestInit | undefined)?.headers as
        Record<string, string> | undefined;
      expect(headers?.Authorization).toBe("Bearer token");
    });
  });
});
