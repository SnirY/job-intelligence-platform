"use client";

import {
  ANALYZED_SENIORITY_LABELS,
  IMPORTANCE_LABELS,
  isAnalysisRunning,
  isMandatory,
  REQUIREMENT_TYPE_LABELS,
  REQUIREMENT_TYPE_ORDER,
  ROLE_FAMILY_LABELS,
  type Job,
  type JobAnalysis,
  type JobAnalysisView,
  type JobRequirement,
  type AnalysisProcessingState,
  type JobStatus,
  type RequirementType,
  type RunningAnalysisStatus,
} from "@jip/shared-types";
import { AlertTriangle, Loader2, Quote, RotateCw, Sparkles } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAnalyzeJob, useJobAnalysis } from "@/features/jobs/api";

/**
 * The intelligence half of the Job Detail screen.
 *
 * `docs/08-ui-ux.md` requires AI output to be visibly distinct from fact, and
 * this whole panel is AI output. Two things keep that honest rather than
 * decorative:
 *
 * - every requirement can show the posting's own words, one click away, so a
 *   reading can always be checked against the source;
 * - judgements (role family, seniority) carry their reasoning and are labelled
 *   as readings, never presented in the same voice as the posting's text.
 *
 * Absent by design: match scores, gaps against the user's profile,
 * recommendations, resume strategy, and application data. None of those exist,
 * and an empty version of each would read as a broken product rather than an
 * unbuilt one.
 */
export function JobIntelligence({ job }: { job: Job }) {
  const [version, setVersion] = useState<number | undefined>(undefined);
  const query = useJobAnalysis(job.id, version);
  const analyze = useAnalyzeJob(job.id);

  if (query.isPending) {
    return <Panel>Loading the analysis…</Panel>;
  }

  if (query.isError || !query.data) {
    return <Panel tone="error">Could not load the analysis for this job.</Panel>;
  }

  const view = query.data;
  const running = isAnalysisRunning(view.job_status);

  // Progress and failure both belong beside the control that caused them.
  // While an analysis is on screen that control is "Analyse again", at the
  // bottom of a list that can run to several screens — and reporting a click
  // there by changing something at the top means reporting it nowhere the
  // person who clicked is looking.
  const attachedToTheReading = Boolean(view.analysis);

  const feedback = (
    <AnalysisFeedback
      status={view.job_status}
      processing={view.processing}
      rejected={analyze.isError}
      retryPending={analyze.isPending}
      onRetry={() => analyze.mutate()}
    />
  );

  return (
    <div className="space-y-4">
      {!attachedToTheReading && feedback}

      {view.analysis ? (
        <AnalysisView
          view={view}
          analysis={view.analysis}
          viewingVersion={version}
          onVersion={setVersion}
          onReanalyze={() => analyze.mutate()}
          reanalyzing={analyze.isPending || running}
          feedback={feedback}
        />
      ) : (
        !running && (
          <EmptyState
            canAnalyze={view.can_analyze}
            pending={analyze.isPending}
            failed={analyze.isError}
            onAnalyze={() => analyze.mutate()}
          />
        )
      )}
    </div>
  );
}

/**
 * What is happening to the analysis right now, wherever it needs to be said.
 *
 * One component for running, failed and refused rather than three rendered in
 * three places, because the rule is about *position*: this is mounted next to
 * whichever button the user pressed, and the caller decides where that is.
 *
 * Renders nothing when there is nothing to report, so a caller can mount it
 * unconditionally.
 */
function AnalysisFeedback({
  status,
  processing,
  rejected,
  retryPending,
  onRetry,
}: {
  status: JobStatus;
  processing: AnalysisProcessingState | null;
  rejected: boolean;
  retryPending: boolean;
  onRetry: () => void;
}) {
  if (isAnalysisRunning(status)) {
    return <RunningNotice status={status} processing={processing} />;
  }

  if (status === "ANALYSIS_FAILED") {
    return (
      <FailedNotice
        message={processing?.error_message ?? null}
        retriable={processing?.is_retriable ?? true}
        pending={retryPending}
        onRetry={onRetry}
      />
    );
  }

  if (rejected) {
    return (
      <Notice tone="warning">
        That could not be started. If an analysis is already running, wait for it to finish and try
        again.
      </Notice>
    );
  }

  return null;
}

function AnalysisView({
  view,
  analysis,
  viewingVersion,
  onVersion,
  onReanalyze,
  reanalyzing,
  feedback,
}: {
  view: JobAnalysisView;
  analysis: JobAnalysis;
  viewingVersion: number | undefined;
  onVersion: (version: number | undefined) => void;
  onReanalyze: () => void;
  reanalyzing: boolean;
  /** Progress, failure, or a refusal — rendered beside the button rather than
      at the top of the panel. With a long requirement list between them, the
      top of the panel is off screen when "Analyse again" is pressed. */
  feedback: React.ReactNode;
}) {
  const isLatest = analysis.version === Math.max(...view.available_versions);

  return (
    <div className="space-y-4">
      {view.is_stale && isLatest && (
        <Notice tone="warning">
          The description has been edited since this was read, so parts of it may no longer match.
          Analysing again will read the current text.
        </Notice>
      )}

      {!isLatest && (
        <Notice>
          You are reading version {analysis.version} of {Math.max(...view.available_versions)}.{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => onVersion(undefined)}
          >
            Show the latest
          </button>
        </Notice>
      )}

      <Overview analysis={analysis} />
      <RoleAndSeniority analysis={analysis} />
      <Requirements requirements={view.requirements} />
      <Responsibilities view={view} />

      {analysis.warnings.length > 0 && <Warnings warnings={analysis.warnings} />}

      <Card>
        <CardContent className="space-y-4 pt-6">
          {feedback}

          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" disabled={reanalyzing} onClick={onReanalyze}>
              <RotateCw aria-hidden className={reanalyzing ? "size-4 animate-spin" : "size-4"} />
              {reanalyzing ? "Analysing…" : "Analyse again"}
            </Button>

            {view.available_versions.length > 1 && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Earlier readings:</span>
                {view.available_versions.map((number) => (
                  <button
                    key={number}
                    type="button"
                    aria-current={number === analysis.version}
                    className={
                      number === analysis.version
                        ? "rounded border px-2 py-0.5 text-xs font-medium"
                        : "rounded border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted"
                    }
                    onClick={() => onVersion(number === viewingVersion ? undefined : number)}
                  >
                    v{number}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Provenance, in small print. Which prompt and model produced a
              reading is what makes a disagreement with it actionable. */}
          <p className="text-xs text-muted-foreground">
            Read by {analysis.model} using {analysis.parse_prompt_version}
            {analysis.analysis_prompt_version && ` and ${analysis.analysis_prompt_version}`}.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Overview({ analysis }: { analysis: JobAnalysis }) {
  const years = formatYears(analysis.years_experience_min, analysis.years_experience_max);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles aria-hidden className="size-4 text-muted-foreground" />
          The opportunity
        </CardTitle>
        <CardDescription>Our reading of the posting, not the posting itself.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {analysis.summary && <p className="text-sm leading-relaxed">{analysis.summary}</p>}

        <dl className="grid gap-4 sm:grid-cols-3">
          {analysis.domain && (
            <div>
              <dt className="text-xs text-muted-foreground">Domain</dt>
              <dd className="text-sm">{analysis.domain}</dd>
            </div>
          )}
          {years && (
            <div>
              <dt className="text-xs text-muted-foreground">Experience asked for</dt>
              <dd className="text-sm">{years}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

function RoleAndSeniority({ analysis }: { analysis: JobAnalysis }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Role and seniority</CardTitle>
        <CardDescription>
          Judgements, each with what it was based on. The posting does not say these directly.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-2">
        <Judgement
          label="Role family"
          value={
            analysis.role_family
              ? ROLE_FAMILY_LABELS[analysis.role_family]
              : "Not clear from the posting"
          }
          secondary={
            analysis.secondary_role_family
              ? `Also ${ROLE_FAMILY_LABELS[analysis.secondary_role_family]}`
              : null
          }
          confidence={analysis.role_family_confidence}
          reasoning={analysis.role_family_reasoning}
        />
        <Judgement
          label="Seniority"
          value={ANALYZED_SENIORITY_LABELS[analysis.seniority]}
          secondary={null}
          confidence={analysis.seniority_confidence}
          reasoning={analysis.seniority_reasoning}
          uncertain={analysis.seniority === "UNKNOWN"}
        />
      </CardContent>
    </Card>
  );
}

function Judgement({
  label,
  value,
  secondary,
  confidence,
  reasoning,
  uncertain,
}: {
  label: string;
  value: string;
  secondary: string | null;
  confidence: number | null;
  reasoning: string | null;
  uncertain?: boolean;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={uncertain ? "text-sm text-muted-foreground" : "text-sm font-medium"}>{value}</p>
      {secondary && <p className="text-xs text-muted-foreground">{secondary}</p>}
      {reasoning && <p className="text-sm leading-relaxed text-muted-foreground">{reasoning}</p>}
      {confidence !== null && !uncertain && <Confidence value={confidence} />}
    </div>
  );
}

/**
 * How sure the reading is.
 *
 * Words rather than a bare percentage: "84%" invites the reader to treat a
 * model's self-report as a measurement. The bands are wide on purpose.
 */
function Confidence({ value }: { value: number }) {
  const label = value >= 80 ? "Clear from the posting" : value >= 50 ? "Fairly clear" : "A guess";

  return (
    <p className="text-xs text-muted-foreground">
      {label} ({value}% confidence)
    </p>
  );
}

function Requirements({ requirements }: { requirements: JobRequirement[] }) {
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
  const mandatory = requirements.filter((r) => isMandatory(r.importance)).length;
  const preferred = requirements.length - mandatory;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Requirements</CardTitle>
        <CardDescription>
          {mandatory} required, {preferred} preferred or optional. Each one can show the
          posting&rsquo;s own words.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {grouped.map(([type, rows]) => (
          <div key={type} className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {REQUIREMENT_TYPE_LABELS[type]}
            </h3>
            <ul className="space-y-2">
              {rows.map((requirement) => (
                <RequirementRow key={requirement.id} requirement={requirement} />
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RequirementRow({ requirement }: { requirement: JobRequirement }) {
  const [open, setOpen] = useState(false);
  const mandatory = isMandatory(requirement.importance);

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm">{requirement.normalized_text}</p>
          {requirement.explicitness === "IMPLIED" && (
            <p className="text-xs text-muted-foreground">
              Implied by the posting rather than stated in it
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {requirement.years_min !== null && (
            <span className="text-xs text-muted-foreground">{requirement.years_min}+ years</span>
          )}
          <Badge variant={mandatory ? "default" : "outline"}>
            {IMPORTANCE_LABELS[requirement.importance]}
          </Badge>
        </div>
      </div>

      <Disclosure
        open={open}
        onToggle={() => setOpen((value) => !value)}
        label="Show the posting's words"
        openLabel="Hide the posting's words"
        icon={<Quote aria-hidden className="size-3 shrink-0" />}
      />

      {open && (
        <blockquote className="mt-2 border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">
          {requirement.source_text}
        </blockquote>
      )}
    </li>
  );
}

function Responsibilities({ view }: { view: JobAnalysisView }) {
  if (view.responsibilities.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What you would do</CardTitle>
        <CardDescription>
          The work itself, as distinct from what you would need before starting.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {view.responsibilities.map((responsibility) => (
            <li key={responsibility.id} className="text-sm leading-relaxed">
              {responsibility.text}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * What validation corrected, in the user's words.
 *
 * Shown rather than hidden: a reading that silently dropped four requirements
 * looks the same as one that found four fewer, and the difference matters when
 * deciding whether to trust it.
 */
function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle aria-hidden className="size-4 text-muted-foreground" />
          Worth knowing about this reading
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-1 text-sm text-muted-foreground">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

const RUNNING_STEPS = {
  PARSING: { number: 1, label: "Reading the posting for what it asks for" },
  ANALYZING: { number: 2, label: "Working out what kind of role this is" },
} as const;

const RUNNING_STEP_COUNT = 2;

/**
 * An analysis in flight.
 *
 * Says which of the two steps is running and how far through, because
 * "working…" for up to a minute with no change is indistinguishable from
 * nothing happening — which is exactly how this read before the status was
 * observable at all (DEV-024).
 */
function RunningNotice({
  status,
  processing,
}: {
  status: RunningAnalysisStatus;
  processing: AnalysisProcessingState | null;
}) {
  const step = RUNNING_STEPS[status];
  const attempt = processing?.attempts ?? 0;

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center gap-3">
          <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />
          <p className="text-sm font-medium" aria-live="polite">
            Step {step.number} of {RUNNING_STEP_COUNT}: {step.label}
          </p>
        </div>

        {/* Two segments rather than a percentage. There are exactly two steps
            and no progress within one, so a moving bar would be inventing
            detail the backend does not have. */}
        <div className="flex gap-1" aria-hidden>
          {[1, 2].map((number) => (
            <div
              key={number}
              className={
                number <= step.number
                  ? "h-1 flex-1 rounded-full bg-primary"
                  : "h-1 flex-1 rounded-full bg-muted"
              }
            />
          ))}
        </div>

        <p className="text-xs text-muted-foreground">
          {attempt > 1
            ? `Attempt ${attempt} — the first one did not work. `
            : "This usually takes under a minute. "}
          The page updates on its own; you can leave it or come back later.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * An analysis that did not work.
 *
 * Distinct from a failed URL import, which offers a paste box. Here the
 * description is intact — telling someone to re-enter text that is already
 * there would be the wrong recovery.
 */
function FailedNotice({
  message,
  retriable,
  pending,
  onRetry,
}: {
  message: string | null;
  retriable: boolean;
  pending: boolean;
  onRetry: () => void;
}) {
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-base">We could not read this posting</CardTitle>
        <CardDescription>
          {message ?? "Something went wrong while analysing it."} Your job and its description are
          untouched.
        </CardDescription>
      </CardHeader>
      {retriable && (
        <CardContent>
          <Button type="button" disabled={pending} onClick={onRetry}>
            <RotateCw aria-hidden className="size-4" />
            {pending ? "Starting…" : "Try again"}
          </Button>
        </CardContent>
      )}
    </Card>
  );
}

function EmptyState({
  canAnalyze,
  pending,
  failed,
  onAnalyze,
}: {
  canAnalyze: boolean;
  pending: boolean;
  failed: boolean;
  onAnalyze: () => void;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 p-6">
        <p className="text-sm font-medium">This job has not been analysed yet.</p>
        <p className="text-sm text-muted-foreground">
          We will read the posting and pull out what it asks for, split into what is required and
          what is preferred, with the original wording kept against each one.
        </p>

        <Button type="button" disabled={!canAnalyze || pending} onClick={onAnalyze}>
          <Sparkles aria-hidden className="size-4" />
          {pending ? "Starting…" : "Analyse this posting"}
        </Button>

        {!canAnalyze && (
          <p className="text-sm text-muted-foreground">
            Add a description first — there is nothing to read yet.
          </p>
        )}

        <p aria-live="polite" className="text-sm text-destructive">
          {failed && "That did not work. Try again in a moment."}
        </p>
      </CardContent>
    </Card>
  );
}

function Panel({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
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
  );
}

function Notice({ children, tone }: { children: React.ReactNode; tone?: "warning" }) {
  return (
    <div
      className={
        tone === "warning"
          ? "rounded-md border border-notice/40 bg-notice/5 p-3 text-sm"
          : "rounded-md border p-3 text-sm text-muted-foreground"
      }
    >
      {children}
    </div>
  );
}

/** Group requirements by type, in the order the reader needs them. */
function groupByType(requirements: JobRequirement[]): [RequirementType, JobRequirement[]][] {
  const groups = new Map<RequirementType, JobRequirement[]>();
  for (const requirement of requirements) {
    const existing = groups.get(requirement.requirement_type);
    if (existing) existing.push(requirement);
    else groups.set(requirement.requirement_type, [requirement]);
  }

  return REQUIREMENT_TYPE_ORDER.filter((type) => groups.has(type)).map((type) => [
    type,
    // Required before preferred within a group: the reader is deciding whether
    // they qualify, and the mandatory items are what answers that.
    [...(groups.get(type) ?? [])].sort(byImportanceThenOrder),
  ]);
}

const IMPORTANCE_RANK = { CORE: 0, REQUIRED: 1, PREFERRED: 2, OPTIONAL: 3, UNKNOWN: 4 };

function byImportanceThenOrder(a: JobRequirement, b: JobRequirement): number {
  const rank = IMPORTANCE_RANK[a.importance] - IMPORTANCE_RANK[b.importance];
  return rank !== 0 ? rank : a.source_order - b.source_order;
}

function formatYears(min: number | null, max: number | null): string | null {
  if (min === null && max === null) return null;
  if (min !== null && max !== null) return `${min}–${max} years`;
  if (min !== null) return `${min}+ years`;
  return `Up to ${max} years`;
}
