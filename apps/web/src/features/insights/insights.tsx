"use client";

import {
  GAP_STATE_HINTS,
  GAP_STATE_LABELS,
  IMPORTANCE_LABELS,
  ROLE_FAMILY_LABELS,
  type FunnelReport,
  type GapState,
  type RequirementImportance,
  type ResumePerformanceReport,
  type RoleReport,
  type SkillDemandEntry,
} from "@jip/shared-types";
import { Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useFunnel,
  useResumePerformance,
  useRoles,
  useSkillDemand,
  useSkillGaps,
} from "@/features/insights/api";
import { SkillReview } from "@/features/insights/skill-review";

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
  const roles = useRoles();
  const funnel = useFunnel();
  const resumes = useResumePerformance();

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
      <Demand skills={report.skills} analysed={report.analysed_jobs} total={report.total_skills} />

      <SkillReview />

      {roles.data && <Roles report={roles.data} />}
      {funnel.data && funnel.data.applications > 0 && <Funnel report={funnel.data} />}
      {resumes.data && resumes.data.versions.length > 0 && <Resumes report={resumes.data} />}
    </div>
  );
}

/**
 * Average alignment per role family.
 *
 * Held back a phase on DEV-026, which said importance moves between readings
 * and therefore poisons any average of scores. Two five-reading measurements
 * found the movement is in which requirements get *extracted*, not in how
 * important they are called — and that varies between alternative readings of
 * one posting, while in production a posting is read once.
 *
 * So this is here, under a threshold, like everything else on the page.
 */
function Roles({ report }: { report: RoleReport }) {
  if (report.roles.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">By role family</CardTitle>
        <CardDescription>
          How the postings you saved group, and how much of each your profile covers. An average
          needs {report.minimum_jobs} jobs in a family before it says anything.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {report.roles.map((role) => (
          <div
            key={role.role_family}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium">{ROLE_FAMILY_LABELS[role.role_family]}</p>
              <p className="text-xs text-muted-foreground">
                {role.jobs === 1 ? "1 job" : `${role.jobs} jobs`}
                {role.applications > 0 && ` · ${role.applications} applied to`}
              </p>
            </div>
            <div className="text-right">
              {/* A dash, never a zero. Below the threshold there is no average,
                  and zero would read as a verdict on fit. */}
              <p className="text-sm font-semibold tabular-nums">
                {role.average_alignment === null ? "—" : `${role.average_alignment}%`}
              </p>
              <p className="text-xs text-muted-foreground">
                {role.average_alignment === null ? "too few to average" : "average alignment"}
              </p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * How far applications have got.
 *
 * Counts always; rates only above the threshold. One application that reached
 * an interview is a 100% interview rate, and there is no honest way to show
 * that — so the counts stay and the division does not happen.
 */
function Funnel({ report }: { report: FunnelReport }) {
  const applied = report.stages.find((stage) => stage.key === "applied")?.reached ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Where applications get to</CardTitle>
        <CardDescription>
          Counted from each application&rsquo;s own history, so one that ended in a rejection still
          counts at every stage it passed through.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {report.stages.map((stage) => (
          <div key={stage.key} className="flex items-center justify-between gap-3 text-sm">
            <span>{stage.label}</span>
            <span className="flex items-center gap-3">
              <span className="font-semibold tabular-nums">{stage.reached}</span>
              {report.rates_are_meaningful && applied > 0 && (
                <span className="w-12 text-right text-xs text-muted-foreground">
                  {Math.round((stage.reached * 100) / applied)}%
                </span>
              )}
            </span>
          </div>
        ))}

        {!report.rates_are_meaningful && (
          <p className="pt-2 text-xs text-muted-foreground">
            Rates need {report.minimum_applications} applications before they mean anything. These
            are counts.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * What happened after each resume version was sent.
 *
 * `docs/07` requires these to read as associations rather than causal claims,
 * and at these sample sizes the word "because" is never available.
 */
function Resumes({ report }: { report: ResumePerformanceReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">By resume version</CardTitle>
        <CardDescription>
          What happened after each was sent. Not a claim that the resume caused it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {report.versions.map((version) => (
          <div
            key={version.resume_version_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
          >
            <span className="font-medium">{version.label}</span>
            <span className="text-xs text-muted-foreground">
              sent {version.sent} · reached interview {version.reached_interview} · offers{" "}
              {version.offers}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
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
    <div className="flex gap-3 rounded-md border border-notice/40 bg-notice/5 p-3 text-sm">
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

function Demand({
  skills,
  analysed,
  total,
}: {
  skills: SkillDemandEntry[];
  analysed: number;
  /** How many were demanded in all. This list is capped; the gaps list is not. */
  total: number;
}) {
  const hidden = total - skills.length;

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
        {hidden > 0 && (
          /* A capped list that does not say it is capped is indistinguishable
             from a complete one. This list is the only one on the screen that
             is short on purpose — the gaps above it are complete. DEV-040. */
          <p className="pt-2 text-sm text-muted-foreground">
            Showing the {skills.length} most asked for, of {total}. The{" "}
            {hidden === 1 ? "other one is" : `other ${hidden} are`} asked for least often; every gap
            is listed above regardless.
          </p>
        )}
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
