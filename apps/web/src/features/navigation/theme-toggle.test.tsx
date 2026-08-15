import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/features/navigation/theme-toggle";

/**
 * DEV-056. `globals.css` carried a full `.dark` palette from Phase 0 and nothing
 * ever added the class, so `docs/08-ui-ux.md`'s "design for both from the
 * beginning" was half true for eleven phases.
 *
 * These assert the control, not the palette — the CSS is verified by the tokens
 * resolving, which is a different question from whether a person can reach them.
 */
function renderToggle() {
  return render(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("theme toggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
  });

  it("starts by following the system rather than choosing for the reader", async () => {
    renderToggle();

    expect(await screen.findByRole("button", { name: "Theme: match system" })).toBeInTheDocument();
  });

  it("cycles system, light, dark and back", async () => {
    const user = userEvent.setup();
    renderToggle();

    await user.click(await screen.findByRole("button", { name: "Theme: match system" }));
    expect(await screen.findByRole("button", { name: "Theme: light" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Theme: light" }));
    expect(await screen.findByRole("button", { name: "Theme: dark" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Theme: dark" }));
    expect(await screen.findByRole("button", { name: "Theme: match system" })).toBeInTheDocument();
  });

  it("puts the class on the document, which is what the palette keys off", async () => {
    const user = userEvent.setup();
    renderToggle();

    await user.click(await screen.findByRole("button", { name: "Theme: match system" }));
    await user.click(await screen.findByRole("button", { name: "Theme: light" }));

    expect(await screen.findByRole("button", { name: "Theme: dark" })).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("names the state it is in, not the state it would move to", async () => {
    // A control announcing "switch to dark" leaves a screen-reader user unable
    // to ask what the theme is *now* — the question the icon answers for
    // everyone else. `docs/08-ui-ux.md` requires that nothing be conveyed by
    // appearance alone.
    const user = userEvent.setup();
    renderToggle();

    await user.click(await screen.findByRole("button", { name: "Theme: match system" }));

    const button = await screen.findByRole("button", { name: "Theme: light" });
    expect(button).toHaveAttribute("title", "Theme: light");
  });
});
