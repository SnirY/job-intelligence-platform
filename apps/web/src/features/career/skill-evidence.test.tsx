import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkillEvidencePanel } from "@/features/career/skill-evidence";

const getToken = vi.fn<() => Promise<string | null>>().mockResolvedValue("token");

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken }),
}));

const SKILL_ID = "6a1f0c2e-0000-4000-8000-000000000001";

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

function renderPanel(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function panel() {
  return <SkillEvidencePanel skillId={SKILL_ID} skillName="Rust" />;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SkillEvidencePanel", () => {
  it("explains what an empty list means rather than just showing nothing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));

    renderPanel(panel());

    // "You have no evidence" is a scolding. The point of the sentence is that
    // the user probably does have some and has never been given anywhere to
    // put it, which is the whole of DEV-054.
    expect(await screen.findByText(/anything that shows where this came from/)).toBeInTheDocument();
  });

  it("lists the reasons already on file with where each came from", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse([
          { id: "e1", source: "MANUAL", note: "Built a ray tracer." },
          { id: "e2", source: "EDUCATION", note: "Compilers course." },
        ]),
      ),
    );

    renderPanel(panel());

    expect(await screen.findByText("Built a ray tracer.")).toBeInTheDocument();
    expect(screen.getByText("Compilers course.")).toBeInTheDocument();
    expect(screen.getByText("You said")).toBeInTheDocument();
    expect(screen.getByText("From your education")).toBeInTheDocument();
  });

  it("posts a trimmed reason and clears the field", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ id: "e1", source: "MANUAL", note: "A course." }))
      .mockResolvedValue(jsonResponse([{ id: "e1", source: "MANUAL", note: "A course." }]));
    vi.stubGlobal("fetch", fetchMock);

    renderPanel(panel());
    const field = await screen.findByLabelText("Add a reason");
    await userEvent.type(field, "  A course.  ");
    await userEvent.click(screen.getByRole("button", { name: /Add/ }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (call) => (call[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({ note: "A course." });
    });
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("will not post a reason that is only whitespace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    renderPanel(panel());
    await userEvent.type(await screen.findByLabelText("Add a reason"), "   ");

    expect(screen.getByRole("button", { name: /Add/ })).toBeDisabled();
  });

  it("offers to remove only the reasons the user typed", async () => {
    // Evidence drawn from a role or a course is a view of that record. Offering
    // a delete here would imply this screen can unpick it, and it cannot —
    // removing it means removing the role.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse([
          { id: "e1", source: "MANUAL", note: "Built a ray tracer." },
          { id: "e2", source: "EXPERIENCE", note: null },
        ]),
      ),
    );

    renderPanel(panel());
    await screen.findByText("Built a ray tracer.");

    expect(screen.getAllByRole("button", { name: /Remove this reason for Rust/ })).toHaveLength(1);
  });

  it("says so when the list cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    renderPanel(panel());

    expect(await screen.findByText(/Could not load your reasons for Rust/)).toBeInTheDocument();
  });
});
