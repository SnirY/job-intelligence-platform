import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A placeholder in the shape of the thing that is coming.
 *
 * The alternative this replaces is a card that says "Loading…", and the job
 * screen renders five of them at once — five cards of different heights that
 * swap to real content one at a time, which guarantees the layout jumps twice
 * before it settles. A skeleton in the final shape reserves the space, so the
 * page arrives rather than assembles.
 *
 * Not a shimmer. `docs/08-ui-ux.md` asks for motion that is functional, and a
 * gradient sweeping across a placeholder answers no question the reader has; it
 * also runs in a loop, which is the one thing the animation rules here forbid.
 * A resting tint is enough to say "not yet".
 */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div aria-hidden className={cn("rounded-md bg-muted", className)} {...props} />;
}

/**
 * The wrapper that announces what is happening while skeletons stand in for it.
 *
 * A skeleton is `aria-hidden`, so on its own it says nothing at all to a screen
 * reader — the visual placeholder and the announcement have to be separate, or
 * the loading state is silent for exactly the readers who cannot see it.
 */
export function SkeletonRegion({
  label,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { label: string }) {
  return (
    <div role="status" aria-live="polite" className={className} {...props}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
