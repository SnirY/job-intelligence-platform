import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileBasicsForm } from "@/features/career/profile-basics-form";

const getToken = vi.fn<() => Promise<string | null>>().mockResolvedValue("token");

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken }),
}));

const emptyProfile = {
  id: "6a1f0c2e-0000-4000-8000-000000000000",
  headline: null,
  professional_summary: null,
  years_of_experience: null,
  current_location: null,
  links: [],
  created_at: "2026-07-26T00:00:00Z",
  updated_at: "2026-07-26T00:00:00Z",
};

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

function renderForm(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

/** Body of the nth fetch call, parsed. */
function requestBody(fetchMock: ReturnType<typeof vi.fn>, index = 1): Record<string, unknown> {
  const [, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProfileBasicsForm", () => {
  it("shows a loading state before the profile arrives", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderForm(<ProfileBasicsForm />);

    expect(screen.getByText(/Loading your profile/)).toBeInTheDocument();
  });

  it("populates the fields from the stored profile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...emptyProfile,
          headline: "Backend engineer",
          years_of_experience: 3,
          links: [{ label: "GitHub", url: "https://github.com/example" }],
        }),
      ),
    );

    renderForm(<ProfileBasicsForm />);

    expect(await screen.findByLabelText("Headline")).toHaveValue("Backend engineer");
    expect(screen.getByLabelText("Years of experience")).toHaveValue(3);
    expect(screen.getByLabelText("Link 1 label")).toHaveValue("GitHub");
  });

  it("keeps save disabled until something actually changes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(emptyProfile)));

    renderForm(<ProfileBasicsForm />);

    const save = await screen.findByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Headline"), "Backend engineer");

    expect(save).toBeEnabled();
  });

  it("sends only the fields that changed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ ...emptyProfile, headline: "Old", current_location: "Tel Aviv" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...emptyProfile, headline: "New", current_location: "Tel Aviv" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderForm(<ProfileBasicsForm />);

    const headline = await screen.findByLabelText("Headline");
    await userEvent.clear(headline);
    await userEvent.type(headline, "New");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    // current_location was untouched, so it must not appear — sending it would
    // overwrite a value edited elsewhere with what this form loaded.
    expect(requestBody(fetchMock)).toEqual({ headline: "New" });
  });

  it("clears a field by sending null rather than an empty string", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ ...emptyProfile, headline: "Backend engineer" }))
      .mockResolvedValueOnce(jsonResponse(emptyProfile));
    vi.stubGlobal("fetch", fetchMock);

    renderForm(<ProfileBasicsForm />);

    await userEvent.clear(await screen.findByLabelText("Headline"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestBody(fetchMock)).toEqual({ headline: null });
  });

  it("reports a failed save instead of appearing to succeed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(emptyProfile))
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({
          error: {
            code: "VALIDATION_ERROR",
            message: "The request payload failed validation.",
            details: null,
            request_id: "req-1",
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    renderForm(<ProfileBasicsForm />);

    await userEvent.type(await screen.findByLabelText("Headline"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/failed validation/)).toBeInTheDocument();
  });

  it("surfaces a load failure rather than an empty form", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderForm(<ProfileBasicsForm />);

    expect(await screen.findByText("Could not load your profile.")).toBeInTheDocument();
  });

  it("adds and removes links", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(emptyProfile)));

    renderForm(<ProfileBasicsForm />);

    await userEvent.click(await screen.findByRole("button", { name: "Add link" }));
    expect(screen.getByLabelText("Link 1 label")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove link 1" }));
    expect(screen.queryByLabelText("Link 1 label")).not.toBeInTheDocument();
  });
});
