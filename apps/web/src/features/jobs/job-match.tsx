"use client";

import {
  FIT_VERDICT_LABELS,
  MATCH_CATEGORY_LABELS,
  PREFERENCE_DIMENSION_LABELS,
  RECOMMENDATION_LABELS,
  type Job,
  type JobMatch,
  type JobMatchView,
  type MatchCategory,
  type MatchItem,
  type PreferenceFit,
} from "@jip/shared-types";
import { AlertOctagon, RotateCw, Target } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StateCard } from "@/components/ui/state-card";
import { Callout } from "@/components/ui/callout";
import { useJobMatch, useMatchJob } from "@/features/jobs/api";
import { CoverageStrip, NextMove } from "@/features/jobs/decision-column";
import { EvidenceChain } from "@/features/jobs/evidence-chain";
import { RequirementField } from "@/features/jobs/requirement-field";

/**
 * The match half of the Job Detail screen.
 *
 * Three panes rather than a scroll. The decision is on the left, the shape of
 * the answer is in the middle, and why one requirement got its verdict is on
 * the right. Choosing a requirement in the field fills the chain, which is what
 * makes the middle pane a navigator rather than a picture — a form that carries
 * meaning in position is only worth the space if position is also how you move.
 *
 * Two things this deliberately never says. It never presents the score as a
 * chance of being hired — `docs/05-ai-and-matching.md` is categorical, so the
 * number always appears next to the word "alignment". And it never shows a
 * status by colour alone: every verdict carries an icon and a label too,
 * because `docs/08-ui-ux.md` requires it and because a red dot means nothing to
 * someone who cannot see red.
 */
export function JobMatchPanel({ job }: { job: Job }) {
  const [version, setVersion] = useState<number | undefined>(undefined);
  const query = useJobMatch(job.id, version);
  const compute = useMatchJob(job.id);

  if (query.isPending) return <StateCard>Loading the match…</StateCard>;
  if (query.isError || !query.data) {
    return <StateCard tone="error">Could not load the match for this job.</StateCard>;
  }

  const view = query.data;

  if (!view.match) {
    return (
      <div className="space-y-6">
        <EmptyState
          canMatch={view.can_match}
          blockingReason={view.blocking_reason}
          pending={compute.isPending}
          failed={compute.isError}
          onMatch={() => compute.mutate()}
        />
        {/* Preferences are about the posting, not about the match, so an
            unmatched job still has an honest answer for them. */}
        <PreferenceFitCard fit={view.preference_fit} />
      </div>
    );
  }

  return (
    <MatchView
      view={view}
      match={view.match}
      viewingVersion={version}
      onVersion={setVersion}
      onRecalculate={() => compute.mutate()}
      recalculating={compute.isPending}
      failed={compute.isError}
    />
  );
}

function MatchView({
  view,
  match,
  viewingVersion,
  onVersion,
  onRecalculate,
  recalculating,
  failed,
}: {
  view: JobMatchView;
  match: JobMatch;
  viewingVersion: number | undefined;
  onVersion: (version: number | undefined) => void;
  onRecalculate: () => void;
  recalculating: boolean;
  /** The last Recalculate failed. The empty state already reported this; a job
      with a match on screen had nowhere to, so the click looked ignored. */
  failed: boolean;
}) {
  const latest = Math.max(...view.available_versions);
  const isLatest = match.version === latest;

  const ordered = [...view.items].sort((a, b) => a.source_order - b.source_order);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fieldView, setFieldView] = useState<"field" | "order">("field");

  const selectedIndex = ordered.findIndex((item) => item.id === selectedId);
  const selected = selectedIndex === -1 ? null : (ordered[selectedIndex] ?? null);
  const blockers = view.items.filter((item) => item.is_blocker);

  return (
    <div className="space-y-4">
      {view.is_stale && isLatest && (
        <Callout tone="caution">
          <p className="font-medium">This match is out of date.</p>
          <ul className="mt-1 space-y-0.5">
            {view.stale_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Callout>
      )}

      {!isLatest && (
        <Callout>
          You are reading version {match.version} of {latest}.{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => onVersion(undefined)}
          >
            Show the latest
          </button>
        </Callout>
      )}

      {/* Three columns from xl up, stacked below it. The field wants seven
          verdict lanes side by side and there is no width at which four of
          them plus a chain and a decision column fit honestly, so the layout
          gives up on columns rather than on lanes. */}
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_400px] xl:items-start">
        <div className="space-y-4">
          <Overview match={match} />
          <CoverageStrip items={view.items} selectedId={selectedId} onSelect={setSelectedId} />
          <NextMove items={view.items} onSelect={setSelectedId} />
          {blockers.length > 0 && <Blockers items={blockers} onOpen={setSelectedId} />}
          <Categories match={match} />
          <PreferenceFitCard fit={view.preference_fit} />
        </div>

        <RequirementField
          items={view.items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          view={fieldView}
          onView={setFieldView}
        />

        <EvidenceChain
          item={selected}
          position={selectedIndex + 1}
          total={ordered.length}
          analysisVersion={match.analysis_version}
          onNext={() => {
            const next = ordered[(selectedIndex + 1) % ordered.length];
            if (next) setSelectedId(next.id);
          }}
        />
      </div>

      {match.warnings.length > 0 && (
        <Callout tone="caution">
          <p className="font-medium">Worth knowing about this match</p>
          <ul className="mt-1 space-y-0.5">
            {match.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Callout>
      )}

      <Card>
        <CardContent className="space-y-4 pt-6">
          {failed && (
            <Callout tone="caution">
              That could not be recalculated. Your existing match is unchanged — try again.
            </Callout>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              disabled={recalculating}
              onClick={onRecalculate}
            >
              <RotateCw aria-hidden className={recalculating ? "size-4 animate-spin" : "size-4"} />
              {recalculating ? "Recalculating…" : "Recalculate"}
            </Button>

            {view.available_versions.length > 1 && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Earlier matches:</span>
                {view.available_versions.map((number) => (
                  <button
                    key={number}
                    type="button"
                    aria-current={number === match.version}
                    className={
                      number === match.version
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

          <p className="text-xs text-muted-foreground">
            Scored deterministically by matching engine {match.engine_version} against reading v
            {match.analysis_version} of the posting. The same profile and posting always produce the
            same number.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Overview({ match }: { match: JobMatch }) {
  return (
    <Card className="border-t-2 border-t-primary">
      <CardContent className="space-y-4 pt-6">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Alignment
        </p>

        <div className="flex items-end gap-3">
          {/* 72px, and the dash that is not a zero. The figure is the one
              thing on this screen that has to survive being glanced at, and it
              spent the whole redesign at the size of a card title. */}
          <p className="font-mono text-[72px] font-semibold leading-[0.9] tracking-tighter tabular-nums">
            {match.overall_score === null ? "—" : match.overall_score}
          </p>
          {/* Never shortened. Invariant 1 wants the number beside the word
              "alignment", and the label is where that word lives. */}
          <p className="pb-1 text-lg font-semibold">{match.alignment_label ?? "Not measured"}</p>
        </div>

        {/* The sentence that keeps the number honest. docs/05-ai-and-matching.md
            forbids presenting a score as a chance of being hired. */}
        <p className="text-xs leading-relaxed text-foreground-faint">
          How much of this posting your profile covers. Not a prediction about interviews or offers.
        </p>

        <div className="flex flex-wrap items-center gap-2.5 border-t pt-4 text-xs">
          {/* Withheld when nothing was scored, for the same reason the score
              itself is null rather than 0: "not measured" is not a verdict.
              The engine still stores a neutral CONSIDER so the column is never
              null, but rendering it put "Worth considering" directly beside
              "There is not enough in your profile yet to compare against this
              job" — a recommendation made on no evidence, next to the sentence
              saying there was none. */}
          {match.overall_score !== null && (
            <Badge variant={match.has_blockers ? "outline" : "default"}>
              {RECOMMENDATION_LABELS[match.recommendation]}
            </Badge>
          )}
          <span className="text-muted-foreground">
            Checked <span className="font-mono text-foreground">{match.scored_requirements}</span>{" "}
            of <span className="font-mono text-foreground">{match.total_requirements}</span>
          </span>
        </div>

        {match.score_cap_reason && (
          <p className="text-sm leading-relaxed text-muted-foreground">{match.score_cap_reason}</p>
        )}

        {match.recommendation_reasons.length > 0 && (
          <ul className="space-y-1 text-sm">
            {match.recommendation_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}

        {match.summary && <p className="text-sm leading-relaxed">{match.summary}</p>}
      </CardContent>
    </Card>
  );
}

/**
 * What the user asked for, against what this posting says.
 *
 * Its own card, below the recommendation and outside it. The score is about
 * evidence and this is about taste, and putting them in one block would invite
 * reading a preference conflict as a worse fit — which it is not. A job you
 * will not take can still be one you are qualified for.
 *
 * Everything is listed, including what nobody set and what the posting does not
 * say. DEV-035's failure was a preference recorded and silently ignored, and a
 * list that quietly omitted the unchecked dimensions would be the same shape.
 */
function PreferenceFitCard({ fit }: { fit: PreferenceFit[] }) {
  // The field is required by the contract and asserted server-side, so an
  // absent one means a client newer than the API it is talking to. Rendering
  // nothing is the right failure: taking down the whole match panel over a
  // secondary block would hide the score, the blockers and the evidence too.
  const rows = fit ?? [];
  if (rows.length === 0) return null;

  const answered = rows.filter(
    (row) => row.verdict !== "NO_PREFERENCE" && row.verdict !== "NOT_COMPARED",
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Against your preferences</CardTitle>
        <CardDescription>
          {answered.length === 0
            ? "You have not set any preferences yet. Settings is where they go."
            : "Separate from the score. A job you will not take can still be one you are qualified for."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.dimension} className="space-y-1 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {PREFERENCE_DIMENSION_LABELS[row.dimension] ?? row.dimension}
                </span>
                <Badge variant={row.verdict === "CONFLICTS" ? "destructive" : "outline"}>
                  {FIT_VERDICT_LABELS[row.verdict]}
                </Badge>
              </div>
              <p className="text-muted-foreground">{row.detail}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * The one thing that should not need finding.
 *
 * The field has a Blocker lane and a blocker is visible in it, but a blocker is
 * the finding that changes what someone does next, and making it something you
 * notice by scanning a column would rank it with everything else. Each one
 * opens its own chain, because "you may know better than we do" is only a fair
 * thing to say if disagreeing with it takes one click.
 */
function Blockers({ items, onOpen }: { items: MatchItem[]; onOpen: (id: string) => void }) {
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertOctagon aria-hidden className="size-4" />
          Blockers
        </CardTitle>
        <CardDescription>
          Listed as essential, and not evidenced in your profile. You may know better than we do.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onOpen(item.id)}
                className="w-full rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
              >
                {item.explanation}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * The score cut a second way.
 *
 * Kept alongside the field because it answers a different question. The field
 * arranges requirements by how much the posting wanted them; this arranges them
 * by what kind of thing they are, and it is the only place a category appears
 * at all.
 */
function Categories({ match }: { match: JobMatch }) {
  const rows = Object.values(match.category_scores).filter((row) => row.score !== null);
  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">By category</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.map((row) => (
          <div key={row.category} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span>{MATCH_CATEGORY_LABELS[row.category as MatchCategory] ?? row.category}</span>
              <span className="font-mono text-muted-foreground tabular-nums">{row.score}%</span>
            </div>
            {/* A bar and a number, because docs/08-ui-ux.md asks for more than
                one representation of a score. */}
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${row.score ?? 0}%` }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function EmptyState({
  canMatch,
  blockingReason,
  pending,
  failed,
  onMatch,
}: {
  canMatch: boolean;
  blockingReason: string | null;
  pending: boolean;
  failed: boolean;
  onMatch: () => void;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 p-6">
        <p className="text-sm font-medium">This job has not been matched yet.</p>
        <p className="text-sm text-muted-foreground">
          We will compare every requirement against your career profile and show you the evidence
          behind each verdict.
        </p>

        <Button type="button" disabled={!canMatch || pending} onClick={onMatch}>
          <Target aria-hidden className="size-4" />
          {pending ? "Matching…" : "Match against my profile"}
        </Button>

        {!canMatch && blockingReason && (
          <p className="text-sm text-muted-foreground">{blockingReason}</p>
        )}

        <p aria-live="polite" className="text-sm text-destructive">
          {failed && "That did not work. Try again in a moment."}
        </p>
      </CardContent>
    </Card>
  );
}
