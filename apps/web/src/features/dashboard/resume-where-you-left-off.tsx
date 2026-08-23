"use client";

import type { ActivityEntry } from "@jip/shared-types";
import Link from "next/link";

/**
 * The last thing somebody did, said as a sentence rather than a row in a list.
 *
 * `/home` is the screen opened without a task, and the list it opened with —
 * "Recently", newest first — answers a question nobody arrives with. What a
 * reader wants first is the thread they put down, and a table of timestamps
 * makes them find it.
 *
 * The register is the whole change. The content was already here.
 *
 * **It says nothing about what is new.** Nothing in the domain records when
 * somebody was last on this screen, so "since your last visit" is unbuildable
 * in every form and a sentence implying it would be inventing a fact. This says
 * when the thing happened and leaves the reader to know whether that was before
 * or after they were here — which they do, and the product does not.
 */
export function WhereYouLeftOff({ entry }: { entry: ActivityEntry | null }) {
  if (!entry) return null;

  const href = entry.job_id ? `/jobs/${entry.job_id}` : null;

  return (
    <section aria-labelledby="left-off-heading" className="rounded-xl border bg-card p-5">
      <h2 id="left-off-heading" className="text-sm text-muted-foreground">
        {when(entry.at)} you were {verbFor(entry.kind)}
      </h2>

      <p className="mt-1.5 text-lg font-semibold tracking-tight">{entry.subject}</p>

      {href && (
        <Link
          href={href}
          className="mt-3 inline-block text-sm font-medium underline underline-offset-4"
        >
          Pick it back up
        </Link>
      )}
    </section>
  );
}

/**
 * "Yesterday afternoon", not a date.
 *
 * A timestamp is what the record holds; a time of day is how somebody
 * remembers putting something down. Anything past the last few days falls back
 * to the date, because "three weeks ago in the afternoon" is precision nobody
 * asked for about a thing they have forgotten.
 */
function when(iso: string): string {
  const at = new Date(iso);
  const days = Math.floor((Date.now() - at.getTime()) / 86_400_000);

  if (days > 6) return at.toLocaleDateString();

  const part = at.getHours() < 12 ? "morning" : at.getHours() < 18 ? "afternoon" : "evening";
  const day =
    days === 0
      ? "This"
      : days === 1
        ? "Yesterday"
        : `${at.toLocaleDateString(undefined, { weekday: "long" })}`;

  return `${day} ${part}`;
}

/**
 * What the entry's kind reads as in a sentence about a person.
 *
 * The seven the feed can actually emit, read off the service rather than
 * guessed: `JOB_SAVED` from the jobs it lists, and the six `ApplicationEvent`
 * types it folds in beside them. A first draft of this map had five entries and
 * four of them named events that do not exist — which is how a screen ends up
 * quietly falling back to a default for every row.
 */
const VERBS: Record<string, string> = {
  JOB_SAVED: "saving",
  CREATED: "starting to track",
  STATUS_CHANGED: "moving",
  RESUME_ATTACHED: "attaching a resume to",
  SUBMITTED: "sending",
  NOTE_ADDED: "making a note on",
  FEEDBACK_RECORDED: "recording feedback on",
};

function verbFor(kind: string): string {
  // Vague rather than wrong. A kind this build does not know is still a real
  // thing somebody did, and "working on" is true of all of them.
  return VERBS[kind] ?? "working on";
}
