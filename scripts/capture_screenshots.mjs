/**
 * Capture the README's screenshots from a seeded demo account.
 *
 *   node scripts/capture_screenshots.mjs
 *
 * A script rather than a folder of one-off captures, because a screenshot is a
 * claim about what the product looks like and that claim goes stale silently.
 * Re-running this after a UI change is the difference between noticing and
 * shipping a README that shows a screen nobody has seen in months.
 *
 * ## What it needs
 *
 * The demo stack, which is deliberately not the development one:
 *
 *   npm run dev:local-auth --workspace @jip/web      # web on 3001, local auth
 *   .venv/Scripts/python.exe -m uvicorn jip_api.main:app --port 8001
 *       with JIP_AUTH_PROVIDER=local, JIP_AUTH_LOCAL_SECRET matching the web's,
 *       and JIP_CORS_ALLOWED_ORIGINS=http://localhost:3001
 *   python scripts/seed_dev_data.py --user demo
 *
 * `.claude/launch.json` carries both servers if you drive them from there.
 *
 * ## Why the demo account and not yours
 *
 * These images are for a public README, and an image cannot be grepped. A real
 * account's jobs and matches would put named employers and this reader's scores
 * against them into a file no later sweep can find — which is the exact problem
 * the 2026-08-30 anonymisation pass existed to fix.
 *
 * The demo account's postings began as real ones and keep their parsed
 * requirements, which is what makes these screens worth looking at: the
 * structured reading is genuine model output over genuine postings. What was
 * replaced is every employer name, and what was dropped is the posting prose
 * itself — unscrubbable free text, and the employers' writing rather than ours.
 *
 * Rows are tagged `[demo]` and `[seed]`, visible in the captures, and that is
 * honest rather than unfortunate: a reader can see the data is a fixture.
 */

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = path.join(ROOT, "docs", "images");

const BASE_URL = process.env.DEMO_BASE_URL ?? "http://localhost:3001";
const SUBJECT = process.env.DEMO_SUBJECT ?? "demo";

/**
 * Which posting the job captures are taken from.
 *
 * This one earns the place: its verdicts include a STRONG_MATCH, a MATCH, a
 * GAP, a NO_EVIDENCE and an UNKNOWN, so one screen shows the whole vocabulary
 * rather than a job that happens to go well.
 */
const JOB_TITLE = process.env.DEMO_JOB_TITLE ?? "Junior Software Engineer, C++";

/** Wide enough that the sidebar and content both read at README width. */
const VIEWPORT = { width: 1440, height: 900 };

/**
 * Each capture names the screen and what it is meant to show, because "the
 * jobs screen" is not a reason to include an image in a README.
 */
const SHOTS = [
  {
    file: "home.png",
    path: "/home",
    shows: "What to do next, each item saying what it is based on",
  },
  {
    file: "job-match.png",
    path: null, // resolved: the job named by JOB_TITLE
    // The opportunity and seniority cards come first on this page; the
    // requirements table is below them, and it is the part worth showing.
    scrollBy: 900,
    shows: "The posting's own words beside our reading, requirement by requirement",
  },
  {
    file: "jobs.png",
    path: "/jobs",
    shows: "Saved postings, with alignment where it has been computed",
  },
  {
    file: "career-profile.png",
    path: "/career-profile",
    shows: "The verified profile every verdict traces back to",
  },
  {
    file: "discovery.png",
    path: "/discovery",
    shows: "Scanned postings waiting for a person to promote them",
  },
];

async function signIn(page) {
  await page.goto(`${BASE_URL}/sign-in`, { waitUntil: "networkidle" });

  const nameField = page.getByLabel("Your name");
  await nameField.waitFor({ state: "visible", timeout: 30_000 });
  await nameField.fill(SUBJECT);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.waitForURL(/\/home/, { timeout: 30_000 });
}

/**
 * A matched job, found by its title rather than a hard-coded id.
 *
 * A plain string, not a regular expression: the title contains `C++`, and `++`
 * in a pattern is a quantifier with nothing to repeat.
 */
async function matchedJobPath(page) {
  await page.goto(`${BASE_URL}/jobs`, { waitUntil: "networkidle" });

  const link = page.getByRole("link", { name: JOB_TITLE }).first();
  await link.waitFor({ state: "visible", timeout: 30_000 });

  const href = await link.getAttribute("href");
  if (!href) throw new Error("Found the matched job but it had no href.");
  return href;
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2, // Retina-density, so the images stay sharp when scaled.
    colorScheme: "light",
  });
  const page = await context.newPage();

  try {
    await signIn(page);
    const jobPath = await matchedJobPath(page);

    for (const shot of SHOTS) {
      const target = shot.path ?? jobPath;
      await page.goto(`${BASE_URL}${target}`, { waitUntil: "networkidle" });

      // Queries resolve after the first paint; without settling, the captures
      // are of loading skeletons rather than of the product.
      await page.waitForTimeout(2_500);

      if (shot.scrollBy) {
        await page.evaluate((y) => window.scrollBy(0, y), shot.scrollBy);
        await page.waitForTimeout(600);
      }

      const file = path.join(OUT_DIR, shot.file);
      await page.screenshot({ path: file, fullPage: false });
      console.log(`  ${shot.file.padEnd(24)} ${shot.shows}`);
    }

    console.log(`\nWrote ${SHOTS.length} images to docs/images/`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`\nCapture failed: ${error.message}`);
  console.error("Is the demo stack up? See this file's header.");
  process.exit(1);
});
