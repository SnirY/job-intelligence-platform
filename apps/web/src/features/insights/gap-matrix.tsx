"use client";

import {
  IMPORTANCE_LABELS,
  isMandatory,
  type RequirementImportance,
  type SkillDemandEntry,
} from "@jip/shared-types";
import { useState } from "react";

/**
 * Every gap placed by how often it was asked for and how firmly.
 *
 * `docs/09-mvp-roadmap.md` lists this as one of four MVP visualisations and it
 * was the one never built. The list it sits beside is ordered worst-first,
 * which answers "what is the worst" and hides the question this form is for:
 * **a gap named once as essential and a gap named twelve times as a preference
 * are different problems, and a ranking puts them in one column.**
 *
 * Both axes are already in the payload, so this reads rather than computes.
 * Across is `jobs`, a count of postings that asked. Up is the firmest wording
 * any of them used, from the `importance` histogram — firmest rather than most
 * common, because one posting calling something essential is the fact that
 * decides whether a gap can block, and an average would bury it.
 *
 * A table is offered beside it, and not as a concession. `docs/08-ui-ux.md`
 * asks every chart for a textual alternative, and the recorded rule here is
 * that a label never lives only on hover — so the table is where every gap is
 * named in full, and the matrix labels the selection rather than the plot.
 */
export function GapMatrix({
  gaps,
  analysed,
}: {
  gaps: SkillDemandEntry[];
  /** The denominator. Sent with every figure so a share is never shown alone. */
  analysed: number;
}) {
  const [view, setView] = useState<"matrix" | "table">("matrix");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  if (gaps.length === 0) return null;

  const placed = gaps.map((gap) => ({ gap, firmest: firmestWording(gap) }));
  const selected = placed.find((row) => row.gap.key === selectedKey) ?? null;

  return (
    <section aria-labelledby="gap-matrix-heading" className="rounded-xl border bg-card">
      <header className="flex flex-wrap items-end justify-between gap-3 px-5 pb-3.5 pt-5">
        <div>
          <h3 id="gap-matrix-heading" className="text-base font-semibold">
            What was asked for, how often, and how firmly
          </h3>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Across: how many of your {analysed} analysed jobs asked for it. Up: how those jobs
            worded it, at its firmest.
          </p>
        </div>

        <div
          role="group"
          aria-label="How to show the gaps"
          className="flex gap-1 rounded-lg border p-0.5"
        >
          {(
            [
              ["matrix", "Matrix"],
              ["table", "Table"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              onClick={() => setView(key)}
              className={
                view === key
                  ? "h-7 rounded-md bg-secondary px-3 text-sm font-medium"
                  : "h-7 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted"
              }
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {view === "matrix" ? (
        <Plot
          placed={placed}
          analysed={analysed}
          selectedKey={selectedKey}
          onSelect={setSelectedKey}
        />
      ) : (
        <Table placed={placed} analysed={analysed} />
      )}

      <Selection selected={selected} analysed={analysed} />
    </section>
  );
}

/**
 * The four quadrants, in the order somebody reads a page.
 *
 * Never dropped, empty or not — the same rule the requirement field keeps. An
 * empty "often, and mandatory" quadrant is the best news this chart can deliver
 * and hiding it removes the one square whose emptiness is the message.
 */
const QUADRANTS = [
  {
    key: "often-firm",
    often: true,
    mandatory: true,
    note: "Asked for often, and worded as mandatory where it appeared",
  },
  {
    key: "rare-firm",
    often: false,
    mandatory: true,
    note: "Asked for rarely, and worded as mandatory where it appeared",
  },
  {
    key: "often-soft",
    often: true,
    mandatory: false,
    note: "Asked for often, and as a preference",
  },
  {
    key: "rare-soft",
    often: false,
    mandatory: false,
    note: "Asked for rarely, and as a preference",
  },
] as const;

type Placed = { gap: SkillDemandEntry; firmest: RequirementImportance };

function Plot({
  placed,
  analysed,
  selectedKey,
  onSelect,
}: {
  placed: Placed[];
  analysed: number;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  /* "Often" is a share of the jobs that were read, not a fixed count. Ten
     postings out of twelve is a pattern; ten out of two hundred is not, and a
     threshold in absolute numbers would call both the same thing. */
  const often = (gap: SkillDemandEntry) => analysed > 0 && gap.jobs * 2 >= analysed;

  return (
    <div className="grid gap-3 px-5 pb-4 sm:grid-cols-2">
      {QUADRANTS.map((quadrant) => {
        const inside = placed.filter(
          (row) =>
            often(row.gap) === quadrant.often && isMandatory(row.firmest) === quadrant.mandatory,
        );

        return (
          <div key={quadrant.key} className="rounded-lg border p-3">
            <p className="text-xs leading-snug text-muted-foreground">{quadrant.note}</p>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{inside.length}</p>

            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {inside.map(({ gap, firmest }) => (
                <button
                  key={gap.key}
                  type="button"
                  aria-pressed={gap.key === selectedKey}
                  /* The name says both axes, because a position says neither to
                     somebody who cannot see it. */
                  aria-label={`${gap.name} — asked for by ${gap.jobs} of ${analysed} jobs, at its firmest ${IMPORTANCE_LABELS[firmest]}`}
                  onClick={() => onSelect(gap.key)}
                  className={
                    gap.key === selectedKey
                      ? "rounded-md border border-primary bg-secondary px-2 py-1 text-sm font-medium ring-1 ring-primary"
                      : "rounded-md border px-2 py-1 text-sm hover:bg-muted"
                  }
                >
                  {gap.name}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Every gap named in full, which the plot deliberately does not do. */
function Table({ placed, analysed }: { placed: Placed[]; analysed: number }) {
  return (
    <div className="overflow-x-auto px-5 pb-4">
      <table className="w-full text-sm">
        <caption className="sr-only">
          Gaps, how many of {analysed} analysed jobs asked for each, and the firmest wording used
        </caption>
        <thead>
          <tr className="border-b text-left">
            <th scope="col" className="py-2 font-medium">
              Skill
            </th>
            <th scope="col" className="py-2 font-medium">
              Asked for by
            </th>
            <th scope="col" className="py-2 font-medium">
              At its firmest
            </th>
          </tr>
        </thead>
        <tbody>
          {placed.map(({ gap, firmest }) => (
            <tr key={gap.key} className="border-b last:border-0">
              <td className="py-2">{gap.name}</td>
              <td className="py-2 font-mono tabular-nums">
                {gap.jobs} of {analysed}
              </td>
              <td className="py-2">{IMPORTANCE_LABELS[firmest]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Selection({ selected, analysed }: { selected: Placed | null; analysed: number }) {
  if (!selected) {
    return (
      <p className="border-t px-5 py-3.5 text-sm text-muted-foreground">
        Pick a gap to see how many postings asked for it and how they worded it.
      </p>
    );
  }

  const { gap, firmest } = selected;

  return (
    <div className="border-t px-5 py-3.5">
      <p className="text-sm font-medium">{gap.name}</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Asked for by <span className="font-mono text-foreground">{gap.jobs}</span> of{" "}
        <span className="font-mono text-foreground">{analysed}</span> analysed jobs. At its firmest,
        worded as {IMPORTANCE_LABELS[firmest].toLowerCase()}.
      </p>
      {!gap.catalogued && (
        /* Said out loud rather than left to the absence of a link. A name the
           catalogue does not hold cannot be added to a profile from here, and a
           reader is entitled to know that is why. */
        <p className="mt-1.5 text-xs text-foreground-faint">
          This name is not in the skill catalogue yet, so it cannot be added to your profile from
          here.
        </p>
      )}
    </div>
  );
}

/**
 * The firmest wording any posting used for this skill.
 *
 * Firmest rather than most common: one posting calling something essential is
 * what decides whether the gap can block an application, and an average would
 * bury exactly that. `UNKNOWN` is the floor, which is honest — a posting that
 * named something without saying how much it mattered has not said "optional".
 */
export function firmestWording(gap: SkillDemandEntry): RequirementImportance {
  const order: RequirementImportance[] = ["CORE", "REQUIRED", "PREFERRED", "OPTIONAL", "UNKNOWN"];
  return order.find((level) => (gap.importance?.[level] ?? 0) > 0) ?? "UNKNOWN";
}
