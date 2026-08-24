import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Going to a page, on a dev server that compiles it while you wait.
 *
 * The first run of this suite failed with `net::ERR_ABORTED; maybe frame was
 * detached?` on a plain `page.goto("/discovery")`, and the trace says why. Next
 * compiles a route the first time anything asks for it. While it compiles, the
 * Fast Refresh client on the page you are still standing on logs
 * `[Fast Refresh] rebuilding` and then reloads that page — and a reload of the
 * old page cancels the navigation to the new one. The network log shows it in
 * order: `GET /discovery` aborted, then `GET /?_rsc=…` — back where we started,
 * with a new build stamp on the stylesheet.
 *
 * Nothing was wrong with the app. The suite was racing the compiler.
 *
 * Two answers, because each covers what the other cannot:
 *
 *   - `warmUp` visits every route the suite uses, once per run, so the compile
 *     happens where a delay is expected rather than inside a test's budget.
 *   - `goTo` retries a navigation the reload cancelled. Warm-up cannot help a
 *     rebuild triggered by anything else, and a retry costs nothing when there
 *     is nothing to retry.
 *
 * Neither hides a real failure: an abort caused by something other than a
 * pending navigation still ends up on the wrong URL, and that is asserted.
 */

/** How long a cold Next compile of one route may take before we call it stuck. */
const COMPILE_TIMEOUT_MS = 60_000;

/** The distinctive shapes a cancelled navigation arrives in. */
const CANCELLED = /ERR_ABORTED|frame was detached|Navigation to .* is interrupted/i;

/**
 * Every route the suite visits, so the compiler is not in the way once
 * assertions start. `/jobs/[jobId]` is reached by clicking rather than by
 * `goto`, and a client-side transition interrupted by a Fast Refresh reload
 * fails in a much less obvious way than this one did — it lands back where it
 * was and the `waitForURL` simply times out. Warming it takes a URL that will
 * not resolve to a job, which is fine: compiling the segment is the whole point
 * and what the page renders for a missing id does not matter here.
 */
const ROUTES = ["/discovery", "/jobs", "/jobs/00000000-0000-0000-0000-000000000000"];

export async function goTo(page: Page, path: string): Promise<void> {
  // Three: one for the cold compile, one for a rebuild that lands badly, and
  // one to be wrong about. More than that and a genuinely broken route would
  // spend a minute pretending to be a slow one.
  const attempts = 3;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const last = attempt === attempts;

    try {
      // `domcontentloaded`, not `load`: `load` waits for Clerk's scripts off
      // their CDN and for every font, none of which any assertion here depends
      // on, and all of which can hang a test for reasons that are not the app.
      await page.goto(path, { waitUntil: "domcontentloaded", timeout: COMPILE_TIMEOUT_MS });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (last || !CANCELLED.test(message)) throw error;
      continue;
    }

    const arrived = new URL(page.url()).pathname;
    if (arrived === path) return;

    // Arrived somewhere else. On the last attempt that is the finding, not a
    // reason to try again — and it is worth saying where, because "signed out
    // and bounced to /sign-in" and "the reload beat us" read identically from
    // a timeout.
    if (last) {
      expect(arrived, explain(path, arrived)).toBe(path);
    }
  }
}

/**
 * Landing on `/sign-in` is worth naming rather than reporting as a wrong URL.
 *
 * It is what a sign-in that only half worked looks like from here: Clerk is
 * happy in the browser, the server sees no session, and `(app)/layout.tsx`
 * redirects. It cost a whole run once, and read as a routing problem.
 */
function explain(wanted: string, arrived: string): string {
  if (arrived === "/sign-in") {
    return (
      `Asked for ${wanted} and was sent to sign in. The browser has no session the ` +
      "server can read, whatever the sign-in step reported — see tests/e2e/signed-in.ts."
    );
  }
  return `Asked for ${wanted} and ended up on ${arrived}.`;
}

export async function warmUp(page: Page): Promise<void> {
  for (const route of ROUTES) {
    await goTo(page, route);
  }
}

/** How long a list gets to arrive before we accept that it is empty. */
const SETTLE_TIMEOUT_MS = 10_000;

/**
 * How many of these there are, once the screen has had the chance to have any.
 *
 * Every list in this app is fetched after the page loads, so counting straight
 * after a navigation counts an empty screen that is still working. A test that
 * does that decides the seed was never run and skips — and a skipped test that
 * should have run is the worst outcome available here, because it reports as a
 * clean run.
 *
 * So: wait for one to exist, then count. If none ever arrives the count is
 * honestly zero, and it cost ten seconds to be sure rather than nothing to be
 * wrong.
 */
export async function countWhenLoaded(locator: Locator): Promise<number> {
  await locator
    .first()
    .waitFor({ state: "attached", timeout: SETTLE_TIMEOUT_MS })
    .catch(() => {
      // Nothing arrived. That is an answer, and the caller's to interpret.
    });
  return locator.count();
}
