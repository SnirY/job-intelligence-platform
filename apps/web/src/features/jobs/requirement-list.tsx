"use client";

import {
  IMPORTANCE_LABELS,
  isMandatory,
  REQUIREMENT_TYPE_LABELS,
  REQUIREMENT_TYPE_ORDER,
  type JobRequirement,
  type RequirementType,
} from "@jip/shared-types";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * What the posting asked for: its words, and our reading of them, side by side.
 *
 * The quote used to sit behind a per-row disclosure labelled "Show the
 * posting's words", so the default state of this list was our normalisation
 * standing alone. `evidence-chain.tsx` states the rule this breaks in its own
 * docstring — the quote and the reading *never render without the other* —
 * and a closed disclosure breaks it on every row at once, which is the version
 * nobody notices.
 *
 * Two columns, then, headed once rather than per row: the posting's sentence on
 * the left in the foreground weight, our reading on the right in the muted one.
 * Invariant 4 is the same rule the evidence chain draws four links for; this is
 * the compact form of it, and the two use one vocabulary on purpose.
 *
 * This is the only part of the analysis panel that leaves the reading column.
 * It earns the width by having two things to set beside each other; the
 * summary, the seniority judgement and the responsibilities are prose and stay
 * where prose belongs.
 */
export function RequirementList({ requirements }: { requirements: JobRequirement[] }) {
  if (requirements.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Requirements</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Nothing in this posting reads as a requirement. That is unusual, and worth checking
            against the original.
          </p>
        </CardContent>
      </Card>
    );
  }

  const grouped = groupByType(requirements);
  const mandatory = requirements.filter((row) => isMandatory(row.importance)).length;
  const preferred = requirements.length - mandatory;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Requirements</CardTitle>
        <CardDescription>
          {/* The old line ended "Each one can show the posting's own words",
              which described the disclosure. Nothing is behind a control now,
              so the sentence says what the columns are instead. */}
          {mandatory} required, {preferred} preferred or optional. The posting&rsquo;s wording and
          our reading of it, side by side.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-7">
        {grouped.map(([type, rows]) => (
          <section key={type} aria-labelledby={`requirements-${type}`} className="space-y-2.5">
            <h3
              id={`requirements-${type}`}
              className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
            >
              {REQUIREMENT_TYPE_LABELS[type]}
            </h3>

            <div className={`${GRID} border-b pb-1.5`}>
              <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                What the posting said
              </span>
              <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                How we read it
              </span>
            </div>

            <ul className="divide-y">
              {rows.map((requirement) => (
                <RequirementRow key={requirement.id} requirement={requirement} />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

/** One template for the header and every row, so the two columns stay aligned. */
const GRID = "grid gap-x-6 gap-y-2 md:grid-cols-2";

function RequirementRow({ requirement }: { requirement: JobRequirement }) {
  return (
    <li className={`${GRID} py-3`}>
      {/* Unedited, and set in the foreground weight. The rule is not that the
          quote is available — it is that the quote is not the quieter of the
          two. */}
      <blockquote className="border-l-2 border-foreground pl-3 text-sm leading-relaxed">
        {requirement.source_text}
      </blockquote>

      <div className="space-y-1.5">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {requirement.normalized_text}
        </p>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <ImportanceTag importance={requirement.importance} />

          {requirement.years_min !== null && (
            <span className="text-muted-foreground">{requirement.years_min}+ years</span>
          )}

          {requirement.explicitness === "IMPLIED" && (
            <span className="text-muted-foreground">
              Implied by the posting rather than stated in it
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * How much the posting insisted — and never in the action colour.
 *
 * This was `Badge variant="default"`, which is `--primary` fill. Primary is
 * what the product uses for the thing you can act on, and on the match screen
 * it is what a selected requirement wears. Spending it on *importance* gives
 * one fill two meanings, and importance is not even a verdict: an Essential
 * requirement the profile covers completely is good news wearing the loudest
 * paint on the screen.
 *
 * `--surface-raised` instead, which is the neutral emphasis the token set
 * already has for exactly this — a thing that stands out without claiming to be
 * a state. Measured 13.4:1 light and 10.7:1 dark for the label on the fill.
 */
function ImportanceTag({ importance }: { importance: JobRequirement["importance"] }) {
  const mandatory = isMandatory(importance);

  return (
    <span
      className={
        mandatory
          ? "inline-flex items-center rounded-md bg-surface-raised px-2 py-0.5 font-medium text-surface-raised-foreground"
          : "inline-flex items-center rounded-md border px-2 py-0.5 text-muted-foreground"
      }
    >
      {IMPORTANCE_LABELS[importance]}
    </span>
  );
}

/** Grouped in the order `REQUIREMENT_TYPE_ORDER` gives, empty groups dropped. */
function groupByType(requirements: JobRequirement[]): Array<[RequirementType, JobRequirement[]]> {
  const buckets = new Map<RequirementType, JobRequirement[]>();
  for (const requirement of requirements) {
    const rows = buckets.get(requirement.requirement_type) ?? [];
    rows.push(requirement);
    buckets.set(requirement.requirement_type, rows);
  }

  return REQUIREMENT_TYPE_ORDER.filter((type) => buckets.has(type)).map((type) => [
    type,
    buckets.get(type) ?? [],
  ]);
}
