"use client";

import type { Job } from "@jip/shared-types";
import { CircleCheck, CircleSlash, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useJob, useJobAction } from "@/features/jobs/api";

/**
 * What a liveness check observed about the posting, and a way to ask again.
 *
 * The rule this component exists to render correctly is invariant 14: **an
 * absent date is not an unknown date.** Both timestamps are null until a check
 * has concluded something, and a check that could not reach the server writes
 * nothing at all. So null means *nobody has looked* — never "still open", and
 * never "closed".
 *
 * That is why the unchecked state is plain muted text with no icon and no
 * colour. A caution badge there would be the product asserting something about
 * a posting on no evidence, which is the same defect invariant 14 was written
 * for after a certification with no expiry date was nearly rendered as expired.
 *
 * Both concluded states carry an icon and a label as well as their colour
 * (invariant 3), and neither states a conclusion the check cannot support: the
 * copy says what the link did and when, not whether the role is gone.
 */

const CHECK_TIMEOUT_MS = 45_000;
/** How long to keep watching before saying so.
 *
 * The check runs on the worker and the API returns before it starts, so there
 * is no completion to await — only a timestamp that may change. A spinner with
 * no end is the state invariant 9 forbids, so waiting is bounded and the
 * timeout is a rendered state of its own rather than a silence. */

export function JobLiveness({ job }: { job: Job }) {
  const [waiting, setWaiting] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const baseline = useRef<string>("");

  // Shares the key `JobDetail` already reads, so this is the cached job — and
  // passing `poll` here drives the refetch for the whole screen while a check
  // is outstanding.
  const query = useJob(job.id, { poll: waiting });
  const check = useJobAction(job.id, "liveness-check");

  const current = query.data ?? job;
  const observed = `${current.last_seen_alive_at ?? ""}|${current.closed_detected_at ?? ""}`;

  // The worker records its answer on the job row and announces nothing, so a
  // finished check is recognised by the observation having moved.
  useEffect(() => {
    if (waiting && observed !== baseline.current) setWaiting(false);
  }, [waiting, observed]);

  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => {
      setWaiting(false);
      setTimedOut(true);
    }, CHECK_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [waiting]);

  // A posting with no link has nothing to check, and the endpoint refuses it.
  if (!current.source_url) return null;

  function start() {
    baseline.current = observed;
    setTimedOut(false);
    check.mutate(undefined, { onSuccess: () => setWaiting(true) });
  }

  const busy = check.isPending || waiting;

  return (
    <div className="mt-4 border-t pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm">
          <Status job={current} busy={busy} />
        </p>

        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={start}>
          <RefreshCw aria-hidden className="size-3.5" />
          {current.last_seen_alive_at || current.closed_detected_at ? "Check again" : "Check"}
        </Button>
      </div>

      {current.closed_detected_at && !busy && (
        <p className="mt-2 text-sm text-muted-foreground">
          The posting may have been filled or withdrawn. This job, its analysis and anything you
          have written stay exactly where they are.
        </p>
      )}

      {timedOut && (
        <p className="mt-2 text-sm text-muted-foreground">
          The check has not come back yet. It may still be running — try again in a moment.
        </p>
      )}

      {check.isError && (
        <p className="mt-2 text-sm text-destructive">
          The check could not be started. Try again shortly.
        </p>
      )}
    </div>
  );
}

function Status({ job, busy }: { job: Job; busy: boolean }) {
  if (busy) {
    return (
      <>
        <Loader2 aria-hidden className="size-4 animate-spin text-muted-foreground" />
        <span className="text-muted-foreground">Checking the link…</span>
      </>
    );
  }

  if (job.closed_detected_at) {
    return (
      <>
        <CircleSlash aria-hidden className="size-4 text-destructive" />
        <span>
          The link returned nothing on <bdi>{formatDate(job.closed_detected_at)}</bdi>
        </span>
      </>
    );
  }

  if (job.last_seen_alive_at) {
    return (
      <>
        <CircleCheck aria-hidden className="size-4 text-muted-foreground" />
        <span>
          The link answered on <bdi>{formatDate(job.last_seen_alive_at)}</bdi>
        </span>
      </>
    );
  }

  // Never checked. Deliberately unadorned — see the note at the top of the file.
  return <span className="text-muted-foreground">This link has not been checked.</span>;
}

/**
 * A date, in the reader's own locale.
 *
 * Always rendered inside `<bdi>`. The copy around it is English and the format
 * is not: on a Hebrew locale this returns a right-to-left run, and dropping one
 * into a left-to-right sentence without isolation reorders it — "The link
 * answered on 23 2026 באוג׳" is what that looks like, and it was found by
 * someone walking the screen rather than by any test.
 */
function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "an unknown date"
    : parsed.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
