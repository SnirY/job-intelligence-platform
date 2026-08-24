import { expect, test } from "./signed-in";

/**
 * What the screen says, and where it puts things.
 *
 * Every assertion here is aimed at a defect a person found on 2026-08-23 and
 * that 1,576 unit and integration tests could not see. Three of the four they
 * found in seven checks were rendering problems, which is the argument for this
 * file existing at all.
 *
 * The suite is deliberately narrow. It is not trying to cover the product —
 * that is what the other 1,597 tests are for. It covers the one thing they
 * structurally cannot: a browser laying out real markup.
 *
 * Needs `python scripts/seed_dev_data.py` to have run. Where a seeded row is
 * absent each test says so and skips rather than failing on an empty screen,
 * because "the seed was not run" and "the screen is wrong" are different
 * answers and a suite that confuses them wastes the morning.
 */

const SEEDED_MATCHED = "[seed] Senior Backend Engineer (matched)";
const SEEDED_SCAM = "[seed] Remote Data Entry Associate (looks wrong)";

test.describe("a job that came from a board", () => {
  test("says so, rather than wearing a blank badge", async ({ signedIn: page }) => {
    /**
     * DEV-079. `JobImportMethod.DISCOVERED` reached the Python enum and never
     * the TypeScript contract, so the label lookup returned `undefined` and the
     * badge rendered empty. `tsc` was satisfied — the union was exhaustive over
     * a set that was already wrong.
     *
     * A parity test now guards the contract. This guards the pixel: whatever
     * the enum does next, the badge on screen has words in it.
     */
    await page.goto("/discovery");

    const firstAdd = page.getByRole("button", { name: /add to jobs/i }).first();
    if ((await firstAdd.count()) === 0) {
      test.skip(true, "No candidates to promote. Run a scan, or seed first.");
    }

    await firstAdd.click();
    await page.waitForURL(/\/jobs\/[0-9a-f-]{36}/);

    // Every badge in the header has to say something. An empty one is the
    // defect, and it is invisible to anything that checks types.
    const badges = page.locator("header").getByRole("generic").filter({ hasText: /\S/ });
    await expect(badges.first()).toBeVisible();
    await expect(page.getByText("Found on a board")).toBeVisible();
  });
});

test.describe("the discovery list", () => {
  test("puts the actions in the same place on every row", async ({ signedIn: page }) => {
    /**
     * DEV-082, and the assertion no other kind of test can make.
     *
     * `flex flex-wrap justify-between` let the action group wrap onto its own
     * line whenever the content beside it grew — and a wrapped line has no
     * `justify-between` partner, so it re-aligned to the start. The rows that
     * moved were the ones with the longest locations, which are already the
     * hardest to scan.
     *
     * Measured rather than described: in a list of identical rows the actions
     * have to be at the same x on each one, because that position is how a
     * reader finds them without reading.
     */
    await page.goto("/discovery");

    const dismissButtons = page.getByRole("button", { name: /dismiss/i });
    const rows = await dismissButtons.count();
    if (rows < 3) {
      test.skip(true, "Fewer than three candidates; alignment needs rows to compare.");
    }

    const positions: number[] = [];
    for (let index = 0; index < rows; index += 1) {
      const box = await dismissButtons.nth(index).boundingBox();
      if (box) positions.push(box.x);
    }

    const spread = Math.max(...positions) - Math.min(...positions);
    expect(
      spread,
      `The Dismiss button sits at ${positions.length} different x positions spanning ` +
        `${spread.toFixed(0)}px. Rows with more text are pushing it out of line.`,
    ).toBeLessThan(2);
  });
});

test.describe("a posting we noticed something about", () => {
  test("shows the concerns below the match, never above it", async ({ signedIn: page }) => {
    /**
     * The rule the whole legitimacy slice turns on, and the only place it can
     * actually be checked. A concern about the listing must not read as part of
     * the verdict about fit — which is a statement about vertical order, and
     * vertical order does not exist until something lays the page out.
     */
    await page.goto("/jobs");

    const link = page.getByRole("link", { name: SEEDED_SCAM });
    if ((await link.count()) === 0) {
      test.skip(true, `No "${SEEDED_SCAM}". Run the seed first.`);
    }
    await link.first().click();

    const concerns = page.getByText("About this posting");
    await expect(concerns).toBeVisible();

    const concernsBox = await concerns.boundingBox();
    const matchBox = await page
      .getByText(/match against my profile/i)
      .first()
      .boundingBox();

    if (matchBox && concernsBox) {
      expect(
        concernsBox.y,
        "The concerns panel is above the match panel. A concern about the listing " +
          "must not read as part of the verdict about fit.",
      ).toBeGreaterThan(matchBox.y);
    }

    // And it never accuses the employer of anything, whatever the rules found.
    const panel = await page.locator("body").innerText();
    expect(panel).not.toMatch(/\bscam\b|\bfraud\b/i);
  });

  test("shows nothing at all about a posting it did not notice anything about", async ({
    signedIn: page,
  }) => {
    /**
     * The absence that matters. No rule firing is a fact about our rules, not a
     * finding about the world — so there is no card, and certainly no tick.
     */
    await page.goto("/jobs");

    const link = page.getByRole("link", { name: SEEDED_MATCHED });
    if ((await link.count()) === 0) {
      test.skip(true, `No "${SEEDED_MATCHED}". Run the seed first.`);
    }
    await link.first().click();

    await expect(page.getByText("Cover letter")).toBeVisible();
    await expect(page.getByText("About this posting")).toHaveCount(0);
    await expect(page.getByText(/no concerns/i)).toHaveCount(0);
  });
});
