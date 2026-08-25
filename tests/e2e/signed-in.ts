import { clerk } from "@clerk/testing/playwright";
import { test as base, type Page } from "@playwright/test";

import { countWhenLoaded, goTo, warmUp } from "./navigate";

/**
 * One signed-in page, for every test in this suite.
 *
 * Signing in through Clerk's own form on every test would be slow, and a
 * failure in it would report as a failure of whatever screen the test was
 * actually about. `@clerk/testing` signs in through Clerk's API instead, which
 * is what makes a browser suite practical here at all.
 *
 * **By sign-in token, not by password.** The first version passed a password
 * and every test landed on `/sign-in`. Clerk had answered the sign-in call with
 * `status: "needs_client_trust"` and no session — the account carries an
 * email-code second factor, a fresh browser context is an unrecognised device
 * every run, and `@clerk/testing` says plainly of its strategy path: multi-
 * factor is not supported. Worse, its `password` branch does not check the
 * status the way its other branches do, so it called `setActive` with nothing,
 * threw nothing, and reported success. The browser was signed out and said so
 * only in a cookie: `__client_uat=0`.
 *
 * Handing it an email address instead takes a different route entirely. It asks
 * Clerk's backend API for a sign-in token and redeems that — server-minted
 * trust, so no factor, no device check, and nothing to type. It also waits for
 * `Clerk.user` to actually exist rather than assuming.
 *
 * So there is no password here and none is needed. `CLERK_SECRET_KEY` does the
 * work, and it is already in `apps/web/.env.local` doing the same job for the
 * running app.
 *
 * **Point it at a throwaway account.** These tests promote and dismiss rows.
 * Running them against the account holding a real career profile would edit
 * somebody's actual job search.
 */

/** Written into every title the seed script creates. */
const SEED_TAG = "[seed]";

/** Compiling every route is a cost the run pays once, not once per test. */
let warmed = false;

/** Whether the account turned out to be the one that was seeded. */
let seedProblem: Error | undefined;

/**
 * What the warm-up may take. Three cold Next compiles inside a container is
 * not fast, and it is charged to whichever test happens to be first — so that
 * test gets the extra budget rather than the whole suite getting a ceiling
 * loose enough to hide a hang.
 */
const WARM_UP_BUDGET_MS = 120_000;

export const test = base.extend<{ signedIn: Page }>({
  signedIn: async ({ page }, use, testInfo) => {
    const emailAddress = process.env.E2E_CLERK_USER_EMAIL;

    if (!emailAddress) {
      throw new Error(
        "E2E_CLERK_USER_EMAIL is not set.\n" +
          "Put the email address of a test account in .env.local at the repository " +
          "root — not the one with your real profile in it. No password is needed: " +
          "sign-in is by token, using the CLERK_SECRET_KEY the app already has.",
      );
    }

    // An unprotected page first: signing in needs Clerk already loaded in the
    // page, and a protected route would have redirected before it could be.
    await goTo(page, "/");
    await clerk.loaded({ page });
    await clerk.signIn({ page, emailAddress });

    if (!warmed) {
      testInfo.setTimeout(testInfo.timeout + WARM_UP_BUDGET_MS);
      await warmUp(page);
      // Only after it worked. A warm-up that threw has warmed nothing, and the
      // next test should pay the cost rather than inherit the problem.
      warmed = true;
      seedProblem = await findSeedProblem(page);
    }

    if (seedProblem) throw seedProblem;

    await use(page);
  },
});

/**
 * Whether this account is the one the seed was run against.
 *
 * Easy to get wrong and, until this existed, silent: `seed_dev_data.py` takes
 * the newest account when nothing tells it otherwise, and the account these
 * tests sign in as is named by a different variable in a different file. Seed
 * one, test the other, and every screen is empty — which reads as four skipped
 * tests and no reason at all.
 *
 * A failure rather than a skip, because "the row this test wanted is gone" and
 * "you tested an account with nothing in it" are not the same answer, and only
 * one of them is a legitimate reason to report nothing and move on.
 */
async function findSeedProblem(page: Page): Promise<Error | undefined> {
  await goTo(page, "/jobs");
  const jobs = await countWhenLoaded(page.getByText(SEED_TAG));

  await goTo(page, "/discovery");
  const candidates = await countWhenLoaded(page.getByText(SEED_TAG));

  if (jobs + candidates > 0) return undefined;

  // The one thing that turns this from a puzzle into a command: the account is
  // known here and nowhere else, and the seed matches on exactly this id.
  const clerkUserId = await page.evaluate(() => window.Clerk?.user?.id ?? "");
  const which = clerkUserId ? `--user ${clerkUserId}` : "--user <this account's Clerk id>";

  return new Error(
    `Signed in as ${process.env.E2E_CLERK_USER_EMAIL}, and that account has nothing ` +
      `seeded — no ${SEED_TAG} jobs and no candidates.\n\n` +
      "The seed takes the newest account unless told otherwise, so seeding one account " +
      "and testing another is the ordinary mistake here. Seed this one:\n\n" +
      `    python scripts/seed_dev_data.py --reset ${which}\n`,
  );
}

/**
 * Skip, and say why somewhere a person will see it.
 *
 * `test.skip(condition, description)` records the description and the list
 * reporter prints a dash. Nothing else. So a suite built on the idea that "the
 * seed was not run" must never look like "the screen is wrong" was reporting
 * both as the same silent dash — which is how a run of four skips reads as a
 * run of four passes.
 */
export function skipBecause(reason: string): never {
  console.log(`\n  Skipped: ${reason}\n`);
  test.skip(true, reason);
  throw new Error("unreachable: test.skip throws");
}

export { expect } from "@playwright/test";
