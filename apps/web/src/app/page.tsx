import { Show } from "@clerk/nextjs";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  CURRENT_PHASE,
  TOTAL_PHASES,
  destinationsByAvailability,
} from "@/features/navigation/destinations";
import { isLocalAuth } from "@/lib/auth-mode";

/** Starts a sentence with a summary written to sit mid-sentence. */
function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "a, b, and c".
 *
 * With the serial comma, unusually for this codebase's prose: several of these
 * summaries contain their own "and", and without it the final two items read as
 * a single clause.
 */
function formatList(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return items.join(" and ");
  return `${items.slice(0, -1).join(", ")}, and ${items.at(-1)}`;
}

/**
 * Public landing page.
 *
 * The only unauthenticated destination that is not part of the sign-in flow.
 * It describes the product and routes onward — it holds no user data.
 */
export default function LandingPage() {
  const { available, upcoming } = destinationsByAvailability();

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-10 px-6 py-16">
      <div className="space-y-4">
        <p className="text-sm font-medium text-muted-foreground">Job Intelligence Platform</p>
        <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
          Understand which roles actually fit you — and why.
        </h1>
        <p className="max-w-xl text-lg text-muted-foreground text-pretty">
          Connect your career profile to real job requirements, see the evidence behind every match,
          and decide where to spend your effort.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {isLocalAuth ? (
          /* Local mode has no account to create and no signed-out widget to
             ask. One button covers both states: /home redirects to /sign-in
             when there is no session, which is the same journey with one fewer
             decision on this page. */
          <Button asChild size="lg">
            <Link href="/home">Open the workspace</Link>
          </Button>
        ) : (
          <>
            {/* Clerk v7 replaced <SignedIn>/<SignedOut> with <Show when=…>. */}
            <Show when="signed-out">
              <Button asChild size="lg">
                <Link href="/sign-up">Create an account</Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/sign-in">Sign in</Link>
              </Button>
            </Show>

            <Show when="signed-in">
              <Button asChild size="lg">
                <Link href="/home">Go to your workspace</Link>
              </Button>
            </Show>
          </>
        )}
      </div>

      {/* Derived, not written out. This paragraph said "Phase 6" for two phases
          after resume tailoring and application tracking had shipped — claiming
          the product did less than it does, which is as misleading as claiming
          more. A comment asking the next person to keep it accurate is not a
          mechanism; reading the same table the navigation reads is. */}
      <p className="text-sm text-muted-foreground">
        In development — Phase {CURRENT_PHASE} of {TOTAL_PHASES}. You can{" "}
        {formatList(available.map((destination) => destination.landingSummary))}.
        {upcoming.length > 0 && (
          <>
            {" "}
            {capitalise(formatList(upcoming.map((d) => d.landingSummary)))}{" "}
            {upcoming.length === 1 ? "is" : "are"} not built yet.
          </>
        )}
      </p>
    </main>
  );
}
