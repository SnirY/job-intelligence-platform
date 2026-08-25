import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests, against a real browser.
 *
 * `active-task.md` carried these as an argument rather than a plan for weeks:
 * eleven of twelve manual walkthrough stages found a defect the automated suite
 * did not, and every one was a correct calculation behind a screen that said the
 * wrong thing. On 2026-08-23 a person walked stage 2.13 and found four more in
 * seven checks. **Three of those four were rendering problems** — a blank badge,
 * a date reordered by the bidirectional algorithm, and a grid column collapsing.
 * No unit or integration test can see any of them. A browser can.
 *
 * So this suite is not "coverage". It is aimed at that one class: what the
 * screen actually says and where it actually puts things.
 *
 * ## What it needs before it will run
 *
 * The stack, up: `docker compose up --build`. These drive the real app against
 * the real API, in the same spirit as the integration tests needing real
 * PostgreSQL rather than a mock.
 *
 * A seeded account: `python scripts/seed_dev_data.py`. Without it the screens
 * are empty and every assertion is vacuous.
 *
 * And one environment variable naming a **test** account — never the one
 * holding a real career profile, because these tests create and delete data:
 *
 * ```text
 * E2E_CLERK_USER_EMAIL=...
 * ```
 *
 * In `.env.local` at the repository root, which `.gitignore` already excludes.
 * No password: sign-in mints a token through Clerk's backend API with the
 * `CLERK_SECRET_KEY` the app already uses, which is also the only way past an
 * account with a second factor. `tests/e2e/signed-in.ts` has the detail.
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  // Serial by default. These share one signed-in account and one database, so
  // parallel workers would race each other through the same rows — and a suite
  // whose failures depend on ordering is one nobody trusts.
  workers: 1,
  fullyParallel: false,
  // No retries. A rendering defect that only appears sometimes is still a
  // rendering defect, and retrying until it passes is how a flaky suite gets
  // built one `retries: 2` at a time.
  retries: 0,
  // 30s was not enough, and not because anything was slow to answer. These run
  // against `next dev`, which compiles a route the first time something asks
  // for it — so the first visit to a screen is a build, not a page load, and a
  // budget sized for a page load reports a compiler as a broken app. `warmUp`
  // in the fixture moves that cost out of the tests; this is the headroom for
  // what it cannot move.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    navigationTimeout: 60_000,
    // On failure only: a trace per run would make the directory the largest
    // thing in the repository within a week.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
