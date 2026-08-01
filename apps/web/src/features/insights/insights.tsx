"use client";

import {
  GAP_STATE_HINTS,
  GAP_STATE_LABELS,
  IMPORTANCE_LABELS,
  type GapState,
  type RequirementImportance,
  type SkillDemandEntry,
} from "@jip/shared-types";
import { Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSkillDemand, useSkillGaps } from "@/features/insights/api";

/**
 * Insights.
 *
 * Two rules from `docs/07-applications-and-career-intelligence.md` shape every
 * sentence here, and both are about not overclaiming:
 *
 * - **"Your observed job market"**, never "the market". The product has no
 *   external market data. Every figure describes the postings this user chose
 *   to save, and saying otherwise would turn a personal reading list into a
 *   claim about an industry.
 * - **Associations, not causal claims.** Nothing here says a skill would get
 *   someone hired.
 *
 * And one from this project's own history: everything is a count. DEV-026
 * measured requirement *importance* moving between two readings of an
 * unchanged posting, so anything averaging or weighting it moves too. Role
 * analysis and the application funnel — both named for this phase — are absent
 * until that is calibrated, rather than shipped with a number that drifts.
 */
export function InsightsScreen() {
  const demand = useSkillDemand();
  const gaps = useSkillGaps();

  if (demand.isPending || gaps.isPending) {
    return <Panel>Reading your saved jobs…</Panel>;
  }

  if (demand.isError || gaps.isError || !demand.data || !gaps.data) {
    return <Panel tone="error">Could not load your insights. Your data is unaffected.</Panel>;
  }

  const report = demand.data;

  if (report.analysed_jobs === 0) {
    return (
      <div className="mx-auto max-w-4xl space-y-6">
        <Header analysed={0} />
        <Card>
          <CardContent className="p-6">
            <p className="text-sm">
              Nothing to read yet. Save a few jobs and have them read into requirements, and this
              page will show what they keep asking for.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Header analysed={report.analysed_jobs} />

      {!report.above_threshold && (
        <Sample analysed={report.analysed_jobs} minimum={report.minimum_jobs} />
      )}

      <Gaps gaps={gaps.data.gaps} analysed={report.analysed_jobs} />
      <Demand skills={report.skills} analysed={report.analysed_jobs} />
    </div>
  );
}

function Header({ analysed }: { analysed: number }) {
  return (
    <header className="space-y-1">
      <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
      <p className="text-muted-foreground">
        {/* "Your observed job market", per docs/07. The product has no external
            market data, and a page that implied otherwise would be describing
            an industry from a reading list of six postings. */}
        What <span className="font-medium">your observed job market</span> keeps asking for — the{" "}
        {analysed === 1 ? "one posting" : `${analysed} postings`} you have saved and had read.
      </p>
    </header>
  );
}

/**
 * The threshold notice.
 *
 * `docs/07` requires explicit minimum-data thresholds. It does not require
 * hiding the figures, and hiding them would be the wrong reading: a user with
 * two saved jobs is entitled to see what those two asked for. What they are not
 * entitled to is a sentence implying it generalises — so the numbers stay and
 * the conclusion is withdrawn.
 */
function Sample({ analysed, minimum }: { analysed: number; minimum: number }) {
  return (
    <div className="flex gap-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
      <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
      <p>
        This is counted over {analysed === 1 ? "one posting" : `${analysed} postings`}. Below{" "}
        {minimum} there is not enough here to call anything a pattern — the counts are real, what
        they add up to is not yet.
      </p>
    </div>
  );
}

function Gaps({ gaps, analysed }: { gaps: SkillDemandEntry[]; analysed: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Asked for, and not evidenced</CardTitle>
        <CardDescription>
          Worst first. A skill missing entirely outranks one you have listed but never attached to a
          role or project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {gaps.length === 0 ? (
          <p className="text-sm">
            Nothing is missing. Every skill these postings named is on your profile and attached to
            real work.
          </p>
        ) : (
          gaps.map((gap) => <SkillRow key={gap.key} skill={gap} analysed={analysed} showState />)
        )}
      </CardContent>
    </Card>
  );
}

function Demand({ skills, analysed }: { skills: SkillDemandEntry[]; analysed: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What comes up most</CardTitle>
        <CardDescription>
          {/* Association, not causation — docs/07 is explicit. This says what
              was asked for, never what would get anyone hired. */}
          How often each skill appears across those postings. Not advice about what to learn.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {skills.map((skill) => (
          <SkillRow key={skill.key} skill={skill} analysed={analysed} />
        ))}
      </CardContent>
    </Card>
  );
}

function SkillRow({
  skill,
  analysed,
  showState = false,
}: {
  skill: SkillDemandEntry;
  analysed: number;
  showState?: boolean;
}) {
  const levels = Object.entries(skill.importance) as [RequirementImportance, number][];

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">
            {skill.name}
            {!skill.catalogued && (
              // The catalogue holds thirty skills and postings name many more.
              // Marked rather than hidden: it is the difference between "two
              // postings asked for this" and "two postings used this word".
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                as written in the posting
              </span>
            )}
          </p>

          {showState && (
            <p className="text-xs text-muted-foreground">{GAP_STATE_HINTS[skill.state]}</p>
          )}

          {levels.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {levels.map(([level, count]) => `${IMPORTANCE_LABELS[level]}: ${count}`).join(" · ")}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {showState && <StateBadge state={skill.state} />}
          <div className="text-right">
            <p className="text-sm font-semibold tabular-nums">
              {skill.jobs} of {analysed}
            </p>
            <p className="text-xs text-muted-foreground">{skill.share}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StateBadge({ state }: { state: GapState }) {
  return (
    <Badge variant={state === "STRONG_GAP" ? "default" : "outline"}>
      {GAP_STATE_LABELS[state]}
    </Badge>
  );
}

function Panel({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
      <Card>
        <CardContent className="p-6">
          <p
            className={
              tone === "error" ? "text-sm text-destructive" : "text-sm text-muted-foreground"
            }
          >
            {children}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
