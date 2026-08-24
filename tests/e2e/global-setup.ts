import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { clerkSetup } from "@clerk/testing/playwright";

/**
 * Fetch Clerk's testing token once, before anything runs.
 *
 * Without it Clerk's bot protection refuses an automated browser, and every
 * test fails at sign-in with an error about the environment rather than about
 * the screen it was testing.
 *
 * The keys already exist in `apps/web/.env.local` — the same ones the dev
 * server uses — so they are read from there rather than asked for twice. The
 * two test-account variables go in `.env.local` at the repository root.
 * Everything is read from files `.gitignore` already excludes; nothing is
 * written here.
 */

const ENV_FILES = [".env.local", "apps/web/.env.local"];

function loadEnvFiles(): void {
  for (const relative of ENV_FILES) {
    let contents: string;
    try {
      contents = readFileSync(resolve(process.cwd(), relative), "utf8");
    } catch {
      // Absent is normal: the root file only exists once somebody has set up
      // the test account, and this should say so at sign-in rather than here.
      continue;
    }

    for (const line of contents.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;

      const separator = trimmed.indexOf("=");
      if (separator < 1) continue;

      const key = trimmed.slice(0, separator).trim();
      // A real environment variable always wins, so a one-off run can override
      // a file without editing it.
      if (process.env[key] !== undefined) continue;

      process.env[key] = trimmed
        .slice(separator + 1)
        .trim()
        .replace(/^["']|["']$/g, "");
    }
  }
}

export default async function globalSetup(): Promise<void> {
  loadEnvFiles();

  // `clerkSetup` reads the publishable key from either name. The web app uses
  // the `NEXT_PUBLIC_` one, so it is copied across rather than duplicated in a
  // second file.
  if (!process.env.CLERK_PUBLISHABLE_KEY && process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    process.env.CLERK_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  }

  if (!process.env.CLERK_SECRET_KEY || !process.env.CLERK_PUBLISHABLE_KEY) {
    throw new Error(
      "Clerk keys not found. They should already be in apps/web/.env.local — " +
        "the same ones the dev server uses.",
    );
  }

  await clerkSetup();
}
