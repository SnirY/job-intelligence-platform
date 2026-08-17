"use client";

import {
  CLAIM_STATUS_LABELS,
  RISK_LABELS,
  SUGGESTION_TYPE_LABELS,
  type Job,
  type ResumeStrategy,
  type ResumeSuggestion,
} from "@jip/shared-types";
import { AlertOctagon, Check, FileText, Pencil, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { StateCard } from "@/components/ui/state-card";
import {
  useCreateStrategy,
  useCreateSuggestions,
  useDecideSuggestion,
  useFinalize,
  useResumes,
  useStrategy,
  useVersions,
} from "@/features/resumes/api";

/**
 * Tailoring a resume for one job, on the Job Detail screen.
 *
 * The four stages `docs/09-mvp-roadmap.md` requires are four visible steps
 * here, deliberately: plan, suggest, review, finalise. A single "tailor my
 * resume" button would be exactly the opaque rewrite the roadmap forbids.
 *
 * The screen's job is to make each suggestion easy to reject. Every one shows
 * what it would change, what it claims, and whether the profile supports that
 * claim — so accepting is a decision rather than a default.
 */
export function JobTailoringPanel({ job }: { job: Job }) {
  const query = useStrategy(job.id);
  const create = useCreateStrategy(job.id);

  if (query.isPending) return <StateCard>Loading the tailoring plan…</StateCard>;
  if (query.isError || !query.data) {
    return <StateCard tone="error">Could not load the tailoring plan.</StateCard>;
  }

  const view = query.data;

  if (!view.strategy) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm font-medium">No tailoring plan for this job yet.</p>
          <p className="text-sm text-muted-foreground">
            We will pick the evidence from your profile that this job actually asked for, then
            suggest changes line by line. Nothing changes without your approval.
          </p>
          <Button
            type="button"
            disabled={!view.can_create || create.isPending}
            onClick={() => create.mutate()}
          >
            <Sparkles aria-hidden className="size-4" />
            {create.isPending ? "Planning…" : "Plan a tailored resume"}
          </Button>
          {!view.can_create && view.blocking_reason && (
            <p className="text-sm text-muted-foreground">{view.blocking_reason}</p>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <StrategyView
      job={job}
      strategy={view.strategy}
      suggestions={view.suggestions}
      blockedCount={view.blocked_count}
      generated={view.suggestions_generated}
      onReplan={() => create.mutate()}
      replanning={create.isPending}
    />
  );
}

function StrategyView({
  job,
  strategy,
  suggestions,
  blockedCount,
  generated,
  onReplan,
  replanning,
}: {
  job: Job;
  strategy: ResumeStrategy;
  suggestions: ResumeSuggestion[];
  blockedCount: number;
  /** Whether the rewriter has run — not whether it produced anything. */
  generated: boolean;
  onReplan: () => void;
  replanning: boolean;
}) {
  const resumes = useResumes();
  const [resumeId, setResumeId] = useState<string>("");
  const chosenResume = resumeId || resumes.data?.[0]?.id || "";
  const versions = useVersions(chosenResume);
  const generate = useCreateSuggestions(job.id, strategy.id);
  const finalize = useFinalize(job.id, strategy.id);

  const draft = versions.data?.find((version) => version.status === "DRAFT");
  const decided = suggestions.filter((s) => s.status !== "PENDING").length;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText aria-hidden className="size-4 text-muted-foreground" />
            Tailoring plan
          </CardTitle>
          <CardDescription>
            What to lead with for this posting, and what your profile does not cover.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {strategy.summary && <p className="text-sm leading-relaxed">{strategy.summary}</p>}

          <div className="grid gap-4 sm:grid-cols-2">
            <List title="Lead with" items={strategy.emphasize} />
            <List title="Cut back" items={strategy.reduce} />
          </div>

          {/* The distinction docs/06 insists on. One is fixable by selecting
              differently; the other is not fixable by any amount of writing. */}
          <div className="grid gap-4 sm:grid-cols-2">
            <List
              title="In your profile, not on this resume"
              description="A resume gap — surface it."
              items={strategy.missing_evidence}
            />
            <List
              title="Not in your profile at all"
              description="A career gap. No rewriting fixes this one."
              items={strategy.career_gaps}
            />
          </div>

          {strategy.warnings.length > 0 && (
            <ul className="space-y-1 text-sm text-muted-foreground">
              {/* Keyed by position, not by text. These are server-supplied
                  sentences with no id, and two of them can be identical — a
                  retried `Suggest changes` used to store the same failure
                  twice. The duplicate is fixed at the source, but a list whose
                  identity depends on its content being unique is one dedupe
                  bug away from dropping a row, and React drops rather than
                  warns in production. */}
              {strategy.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}

          <Button type="button" variant="ghost" size="sm" disabled={replanning} onClick={onReplan}>
            {replanning ? "Planning…" : "Plan again"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Suggestions</CardTitle>
          <CardDescription>
            One change at a time, each checked against your profile before you see it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="tailor-resume">Resume to tailor</Label>
              <Select
                id="tailor-resume"
                className="w-56"
                value={chosenResume}
                onChange={(event) => setResumeId(event.target.value)}
              >
                {(resumes.data ?? []).map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.title}
                  </option>
                ))}
              </Select>
            </div>

            <Button
              type="button"
              disabled={!draft || generate.isPending}
              onClick={() => draft && generate.mutate(draft.id)}
            >
              <Sparkles aria-hidden className="size-4" />
              {generate.isPending ? "Thinking…" : "Suggest changes"}
            </Button>
          </div>

          {!draft && chosenResume && (
            <p className="text-sm text-muted-foreground">
              That resume has no draft version to work on. Create one on the Resumes page first.
            </p>
          )}

          {blockedCount > 0 && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 p-3 text-sm">
              <AlertOctagon aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
              <p>
                {blockedCount} suggestion{blockedCount === 1 ? "" : "s"} would say something your
                profile does not support. Read those carefully — if the detail is real, add it to
                your profile rather than only to this resume.
              </p>
            </div>
          )}

          {suggestions.length === 0 ? (
            generated ? (
              // A real answer, not an absence. The rewriter is told to leave a
              // line alone when it is already good, so nothing to propose is a
              // result — and reporting it the same way as "you have not asked
              // yet" was what made Stage 2.8.6 unreadable.
              <div className="flex items-start gap-2 rounded-md border p-3 text-sm">
                <Check aria-hidden className="mt-0.5 size-4 shrink-0" />
                <p>
                  Nothing to change. We looked at every line against this posting and did not find
                  wording worth altering — your resume can go as it is.
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No suggestions yet. Choose a resume above and generate them.
              </p>
            )
          ) : (
            <ul className="space-y-3">
              {suggestions.map((suggestion) => (
                <SuggestionRow key={suggestion.id} jobId={job.id} suggestion={suggestion} />
              ))}
            </ul>
          )}

          {suggestions.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 border-t pt-4">
              <Button
                type="button"
                disabled={finalize.isPending || !chosenResume}
                onClick={() =>
                  finalize.mutate({ resume_id: chosenResume, label: `Tailored for ${job.title}` })
                }
              >
                {finalize.isPending ? "Creating…" : "Create the tailored version"}
              </Button>
              <p className="text-sm text-muted-foreground">
                {decided} of {suggestions.length} reviewed. Only accepted and edited changes are
                applied; anything still pending is left alone.
              </p>
              {finalize.isSuccess && (
                <p className="text-sm text-muted-foreground">
                  Created version {finalize.data.version} with {finalize.data.applied} change
                  {finalize.data.applied === 1 ? "" : "s"}.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SuggestionRow({ jobId, suggestion }: { jobId: string; suggestion: ResumeSuggestion }) {
  const decide = useDecideSuggestion(jobId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(suggestion.suggested_text);

  const settled = suggestion.status !== "PENDING";
  const textChanged =
    (suggestion.final_text ?? suggestion.suggested_text) !== suggestion.original_text;

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-2">
          {/* A REORDER proposes no new words — the line moves, the text stays.
              Striking through the original above an identical replacement reads
              as "delete this and put it back", so the before/after is shown
              only when there is a difference to see. */}
          {suggestion.original_text && textChanged && (
            <p className="text-xs text-muted-foreground line-through">{suggestion.original_text}</p>
          )}
          <p className="text-sm">{suggestion.final_text ?? suggestion.suggested_text}</p>
          {suggestion.rationale && (
            <p className="text-xs text-muted-foreground">{suggestion.rationale}</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{SUGGESTION_TYPE_LABELS[suggestion.suggestion_type]}</Badge>
          <Badge variant={suggestion.risk === "LOW" ? "outline" : "default"}>
            {RISK_LABELS[suggestion.risk]}
          </Badge>
          {settled && <Badge variant="outline">{suggestion.status.toLowerCase()}</Badge>}
        </div>
      </div>

      {suggestion.claims.some((claim) => claim.status !== "SAFE") && (
        <ul className="mt-2 space-y-1 border-l-2 pl-3">
          {suggestion.claims
            .filter((claim) => claim.status !== "SAFE")
            .map((claim) => (
              <li key={claim.id} className="text-xs">
                <span className={claim.status === "BLOCKED" ? "text-destructive" : ""}>
                  {CLAIM_STATUS_LABELS[claim.status]}:
                </span>{" "}
                {claim.explanation}
              </li>
            ))}
        </ul>
      )}

      {!settled && (
        <div className="mt-3 space-y-2">
          {editing && (
            <Textarea
              className="min-h-20 text-sm"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={decide.isPending}
              onClick={() =>
                editing
                  ? decide.mutate({ id: suggestion.id, decision: "edit", text })
                  : decide.mutate({ id: suggestion.id, decision: "accept" })
              }
            >
              <Check aria-hidden className="size-4" />
              {editing ? "Use my wording" : "Accept"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={decide.isPending}
              onClick={() => setEditing((value) => !value)}
            >
              <Pencil aria-hidden className="size-4" />
              {editing ? "Cancel" : "Edit"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: suggestion.id, decision: "reject" })}
            >
              <X aria-hidden className="size-4" />
              Reject
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function List({
  title,
  description,
  items,
}: {
  title: string;
  description?: string;
  items: string[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
      <ul className="space-y-1 text-sm">
        {/* Keyed by position for the same reason as the warnings above: these
            are server-supplied strings with no id, and nothing guarantees a
            gap or a missing-evidence line is unique. */}
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
