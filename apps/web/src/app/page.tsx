import { Show } from "@clerk/nextjs";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * Public landing page.
 *
 * The only unauthenticated destination that is not part of the sign-in flow.
 * It describes the product and routes onward — it holds no user data.
 */
export default function LandingPage() {
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
      </div>

      {/* Kept accurate as phases land. A page claiming less than the product
          does is as misleading as one claiming more. */}
      <p className="text-sm text-muted-foreground">
        In development — Phase 5 of 11. You can build a career profile, import one from a resume,
        save jobs, and have a posting read into its requirements. Matching a profile against a job
        is not built yet.
      </p>
    </main>
  );
}
