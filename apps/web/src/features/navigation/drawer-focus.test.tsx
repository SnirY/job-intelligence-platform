import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "@/features/navigation/app-shell";

/**
 * The mobile drawer's focus contract — F31, tested where it was recorded.
 *
 * That entry is cited in the command palette and the confirm dialog as the
 * reason both restore focus. The drawer it was written about had none of it:
 * `aria-modal="true"` over an untrapped panel, no focus on open, and none
 * returned on close.
 *
 * Escape it did handle, on a window listener. The two Escape cases below
 * therefore passed before this change and pass after it, and they are kept as
 * the record of which part of the contract was already met — with the note that
 * they discriminate nothing on their own. The three that failed are the fix.
 *
 * It survived because nothing asserted it. The palette and the dialog were
 * built later, with tests, and the older overlay kept the defect that justified
 * their tests.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
  UserButton: () => <button type="button">Account</button>,
  useUser: () => ({ user: { firstName: "Alex" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/jobs",
}));

/** The shell mounts the command palette, which queries. */
function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AppShell>
        <p>Page</p>
      </AppShell>
    </QueryClientProvider>,
  );
}

async function openDrawer() {
  const opener = screen.getByRole("button", { name: "Open menu" });
  await userEvent.click(opener);
  return { opener, drawer: screen.getByRole("dialog", { name: "Main menu" }) };
}

describe("the mobile drawer", () => {
  it("takes focus when it opens, and puts it on the way out", async () => {
    /* Not the first navigation link. A drawer's first act should be to say how
       to leave it, and somebody who opened a menu by mistake is then one key
       from undoing that. */
    renderShell();

    const { drawer } = await openDrawer();

    expect(drawer.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(within(drawer).getByRole("button", { name: "Close menu" }));
  });

  it("keeps Tab inside while it is open", async () => {
    /* `aria-modal="true"` promises a screen reader that what is behind is
       unreachable. Tab walking out makes that promise false, which is worse
       than never making it: the reader is told they are somewhere they are
       not. */
    renderShell();

    const { drawer } = await openDrawer();

    for (let press = 0; press < 10; press += 1) {
      await userEvent.tab();
      expect(drawer.contains(document.activeElement)).toBe(true);
    }
  });

  it("closes on Escape", async () => {
    renderShell();

    await openDrawer();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Main menu" })).not.toBeInTheDocument();
  });

  it("returns focus to the button that opened it", async () => {
    // F31 itself. Without this a keyboard reader lands back at the top of the
    // document with no memory of where they were.
    renderShell();

    const { opener, drawer } = await openDrawer();
    await userEvent.click(within(drawer).getByRole("button", { name: "Close menu" }));

    expect(document.activeElement).toBe(opener);
  });

  it("returns focus when it is dismissed by Escape too", async () => {
    renderShell();

    const { opener } = await openDrawer();
    await userEvent.keyboard("{Escape}");

    expect(document.activeElement).toBe(opener);
  });
});
