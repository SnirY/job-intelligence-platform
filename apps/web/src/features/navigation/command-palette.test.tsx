import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/features/navigation/command-palette";

const push = vi.fn();

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function renderWithQuery(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function serving(rows: unknown[]) {
  return vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      data: rows,
      meta: { page: 1, page_size: 6, total: rows.length, total_pages: 1 },
    }),
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("the command palette", () => {
  it("stays out of the way until the key is pressed", () => {
    vi.stubGlobal("fetch", serving([]));

    renderWithQuery(<CommandPalette />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on ctrl or meta K, on either kind of keyboard", async () => {
    /* Bound to both rather than chosen by platform: a Windows keyboard on a Mac
       and a Mac keyboard on Linux are both ordinary, and guessing wrong costs
       the shortcut entirely. */
    vi.stubGlobal("fetch", serving([]));

    renderWithQuery(<CommandPalette />);

    await userEvent.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.keyboard("{Meta>}k{/Meta}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("returns focus to where it came from", async () => {
    /* F31 recorded this against the mobile drawer: a dialog that takes focus and
       does not give it back leaves a keyboard reader at the top of the
       document. */
    vi.stubGlobal("fetch", serving([]));

    renderWithQuery(
      <>
        <button type="button">Opener</button>
        <CommandPalette />
      </>,
    );

    const opener = screen.getByRole("button", { name: "Opener" });
    opener.focus();

    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");

    expect(opener).toHaveFocus();
  });

  it("jumps to a screen without the mouse", async () => {
    vi.stubGlobal("fetch", serving([]));

    renderWithQuery(<CommandPalette />);
    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog");

    await userEvent.keyboard("Applications");
    await userEvent.keyboard("{Enter}");

    expect(push).toHaveBeenCalledWith("/applications");
  });

  it("lists no jobs until there is something to search by", async () => {
    /* An empty palette offering six arbitrary jobs would be a list, and there
       is already a list. */
    vi.stubGlobal(
      "fetch",
      serving([{ id: "job-1", title: "Senior Backend Engineer", company: "Verdant" }]),
    );

    renderWithQuery(<CommandPalette />);
    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog");

    expect(screen.queryByText("Senior Backend Engineer")).not.toBeInTheDocument();

    await userEvent.keyboard("Backend");
    expect(await screen.findByText("Senior Backend Engineer")).toBeInTheDocument();
  });

  it("says plainly when nothing matches", async () => {
    vi.stubGlobal("fetch", serving([]));

    renderWithQuery(<CommandPalette />);
    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog");

    await userEvent.keyboard("zzzz");

    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument();
  });
});
