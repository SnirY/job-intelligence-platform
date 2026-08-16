import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkillReview } from "@/features/insights/skill-review";

const getToken = vi.fn<() => Promise<string | null>>().mockResolvedValue("token");

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken }),
}));

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

/**
 * A mock that answers by method, the way the API does.
 *
 * The list endpoint returns an array and the decision endpoints return one
 * object. A single `mockResolvedValue` for both makes the refetch after a
 * decision hand the component an object, which crashes it — an artifact of the
 * mock rather than a defect, and one that hides real failures behind noise.
 */
function routedFetch(list: unknown[], decided: unknown) {
  return vi.fn((_url: string, init?: RequestInit) =>
    Promise.resolve(jsonResponse(init?.method === "POST" ? decided : list)),
  );
}

function renderReview(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const CAN = {
  id: "c1",
  normalized_name: "can",
  display_name: "CAN",
  occurrences: 1,
  status: "PENDING" as const,
  resolved_skill_id: null,
  note: null,
  example_source_text:
    "Knowledge of communication protocols such as UART, SPI, I2C, TCP/IP, or CAN",
  example_job_title: "Junior Embedded C++ Developer",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SkillReview", () => {
  it("shows the sentence the name came from", async () => {
    // The reason the context fields exist. "CAN" is a three-letter string that
    // is also an ordinary English word; without the sentence a reviewer is
    // being asked to guess, which is a screen presenting a result rather than
    // enabling a decision.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([CAN])));

    renderReview(<SkillReview />);

    expect(await screen.findByText("CAN")).toBeInTheDocument();
    expect(screen.getByText(/UART, SPI, I2C, TCP\/IP, or CAN/)).toBeInTheDocument();
    expect(screen.getByText("Junior Embedded C++ Developer")).toBeInTheDocument();
  });

  it("says how many postings use the name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([{ ...CAN, occurrences: 6 }])));

    renderReview(<SkillReview />);

    expect(await screen.findByText("6 postings")).toBeInTheDocument();
  });

  it("an empty queue reads as resolved, not as broken", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));

    renderReview(<SkillReview />);

    expect(
      await screen.findByText(/Every technology your postings named resolves/),
    ).toBeInTheDocument();
  });

  it("posts a rejection", async () => {
    const fetchMock = routedFetch([CAN], { ...CAN, status: "REJECTED" });
    vi.stubGlobal("fetch", fetchMock);

    renderReview(<SkillReview />);
    await userEvent.click(await screen.findByRole("button", { name: /Not a skill: CAN/ }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((entry) => String(entry[0]).endsWith("/reject"));
      expect(call).toBeDefined();
    });
  });

  it("adds to the catalogue with a corrected name and a category", async () => {
    const fetchMock = routedFetch([CAN], { ...CAN, status: "ACCEPTED" });
    vi.stubGlobal("fetch", fetchMock);

    renderReview(<SkillReview />);
    await userEvent.click(await screen.findByRole("button", { name: /Add to catalogue/ }));

    const name = screen.getByLabelText("Catalogue name");
    await userEvent.clear(name);
    await userEvent.type(name, "CAN bus");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "PLATFORM");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((entry) => String(entry[0]).endsWith("/accept-new"));
      expect(call).toBeDefined();
      const body = JSON.parse((call![1] as RequestInit).body as string) as Record<string, unknown>;
      expect(body).toEqual({ category: "PLATFORM", canonical_name: "CAN bus" });
    });
  });

  it("will not add a blank catalogue name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([CAN])));

    renderReview(<SkillReview />);
    await userEvent.click(await screen.findByRole("button", { name: /Add to catalogue/ }));
    await userEvent.clear(screen.getByLabelText("Catalogue name"));

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("says so when the queue cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    renderReview(<SkillReview />);

    expect(await screen.findByText(/Could not load the queue/)).toBeInTheDocument();
  });
});
