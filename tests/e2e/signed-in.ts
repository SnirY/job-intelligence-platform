import { clerk } from "@clerk/testing/playwright";
import { test as base, type Page } from "@playwright/test";

import { goTo, warmUp } from "./navigate";

/**
 * One signed-in page, for every test in this suite.
 *
 * Signing in through Clerk's own form on every test would be slow, and a
 * failure in it would report as a failure of whatever screen the test was
 * actually about. `@clerk/testing` signs in through Clerk's API instead, which
 * is what makes a browser suite practical here at all.
 *
 * It needs a strategy Clerk accepts headlessly — `password`, `email_code` or
 * `phone_code`. An account created through Google alone has none of them, and
 * there would be nothing left but driving Google's consent screen, which is the
 * thing test tooling cannot do reliably. This uses `password`.
 *
 * **Point it at a throwaway account.** These tests create and dismiss rows.
 * Running them against the account holding a real career profile would edit
 * somebody's actual job search.
 */

/** Compiling every route is a cost the run pays once, not once per test. */
let warmed = false;

/**
 * What the warm-up may take. Three cold Next compiles inside a container is
 * not fast, and it is charged to whichever test happens to be first — so that
 * test gets the extra budget rather than the whole suite getting a ceiling
 * loose enough to hide a hang.
 */
const WARM_UP_BUDGET_MS = 120_000;

export const test = base.extend<{ signedIn: Page }>({
  signedIn: async ({ page }, use, testInfo) => {
    const identifier = process.env.E2E_CLERK_USER_IDENTIFIER;
    const password = process.env.E2E_CLERK_USER_PASSWORD;

    if (!identifier || !password) {
      throw new Error(
        "E2E_CLERK_USER_IDENTIFIER and E2E_CLERK_USER_PASSWORD are not set.\n" +
          "Put them in .env.local at the repository root — a test account, not the " +
          "one with your real profile in it.",
      );
    }

    // An unprotected page first: `clerk.signIn` needs Clerk already loaded in
    // the page, and a protected route would have redirected before it could be.
    await goTo(page, "/");
    await clerk.loaded({ page });
    await clerk.signIn({
      page,
      signInParams: { strategy: "password", identifier, password },
    });

    if (!warmed) {
      testInfo.setTimeout(testInfo.timeout + WARM_UP_BUDGET_MS);
      await warmUp(page);
      // Only after it worked. A warm-up that threw has warmed nothing, and the
      // next test should pay the cost rather than inherit the problem.
      warmed = true;
    }

    await use(page);
  },
});

export { expect } from "@playwright/test";
