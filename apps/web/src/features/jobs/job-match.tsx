"use client";

import {
  isPositiveMatch,
  MATCH_CATEGORY_LABELS,
  MATCH_STATUS_LABELS,
  MATCH_STATUS_TONE,
  RECOMMENDATION_LABELS,
  type Job,
  type JobMatch,
  type JobMatchView,
  type MatchCategory,
  type MatchItem,
  type MatchStatus,
} from "@jip/shared-types";
import {
  AlertOctagon,
  ArrowLeftRight,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  MinusCircle,
  RotateCw,
  Target,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useJobMatch, useMatchJob } from "@/features/jobs/api";

/**
 * The match half of the Job Detail screen.
 *
 * Two things this deliberately never says. It never presents the score as a
 * chance of being hired — `docs/05-ai-and-matching.md` is categorical, so the
 * number always appears next to the word "alignment". And it never shows a
 * status by colour alone: every verdict carries an icon and a label too,
 * because `docs/08-ui-ux.md` requires it and because a red dot means nothing to
 * someone who cannot see red.
 *
 * The evidence drawer is the point of the screen. `docs/08-ui-ux.md` asks that
 * a user be able to ask "why does the system think I match this?" and see the
 * exact evidence, so every requirement opens to show the career rows behind it.
 */
export function JobMatchPanel({ job }: { job: Job }) {
  const [version, setVersion] = useState<number | undefined>(undefined);
  const query = useJobMatch(job.id, version);
  const compute = useMatchJob(job.id);

  if (query.isPending) return <Panel>Loading the match…</Panel>;
  if (query.isError || !query.data) {
    return <Panel tone="error">Could not load the match for this job.</Panel>;
  }

  const view = query.data;

  if (!view.match) {
    return (
      <EmptyState
        canMatch={view.can_match}
        blockingReason={view.blocking_reason}
        pending={compute.isPending}
        failed={compute.isError}
        onMatch={() => compute.mutate()}
      />
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

  const blockers = view.items.filter((item) => item.is_blocker);
  const strengths = view.items
    .filter((item) => item.status === "STRONG_MATCH" || item.status === "MATCH")
    .sort((a, b) => b.weight - a.weight);
  const gaps = view.items.filter((item) => item.status === "GAP");
  const transferable = view.items.filter((item) => item.status === "TRANSFERABLE_MATCH");

  return (
    <div className="space-y-4">
      {view.is_stale && isLatest && (
        <Notice tone="warning">
          <p className="font-medium">This match is out of date.</p>
          <ul className="mt-1 space-y-0.5">
            {view.stale_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Notice>
      )}

      {!isLatest && (
        <Notice>
          You are reading version {match.version} of {latest}.{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => onVersion(undefined)}
          >
            Show the latest
          </button>
        </Notice>
      )}

      <Overview match={match} />

      {blockers.length > 0 && <Blockers items={blockers} />}

      <Categories match={match} />

      {strengths.length > 0 && (
        <Highlights
          title="What lines up"
          description="Requirements your profile already covers."
          items={strengths.slice(0, 5)}
        />
      )}

      {transferable.length > 0 && (
        <Highlights
          title="Related, but not the same"
          description="Experience that should transfer without being what the posting named."
          items={transferable}
        />
      )}

      {gaps.length > 0 && (
        <Highlights
          title="Gaps"
          description="Asked for, and not evidenced in your profile."
          items={gaps.slice(0, 5)}
        />
      )}

      <Requirements items={view.items} />

      {match.warnings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Worth knowing about this match</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm text-muted-foreground">
              {match.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-4 pt-6">
          {failed && (
            <Notice tone="warning">
              That could not be recalculated. Your existing match is unchanged — try again.
            </Notice>
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Target aria-hidden className="size-4 text-muted-foreground" />
          How you line up
        </CardTitle>
        <CardDescription>
          {/* The sentence that keeps the number honest. docs/05-ai-and-matching.md
              forbids presenting a score as a chance of being hired. */}
          How much of this posting your profile covers. Not a prediction about interviews or offers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-6">
          <div>
            <p className="text-4xl font-semibold tabular-nums">
              {match.overall_score === null ? "—" : `${match.overall_score}%`}
            </p>
            <p className="text-sm text-muted-foreground">{match.alignment_label}</p>
          </div>

          {/* Withheld when nothing was scored, for the same reason the score
              itself is null rather than 0: "not measured" is not a verdict.
              The engine still stores a neutral CONSIDER so the column is never
              null, but rendering it put "Worth considering" directly beside
              "There is not enough in your profile yet to compare against this
              job" — a recommendation made on no evidence, next to the sentence
              saying there was none. */}
          {match.overall_score !== null && (
            <div>
              <p className="text-xs text-muted-foreground">Recommendation</p>
              <Badge variant={match.has_blockers ? "outline" : "default"} className="mt-1">
                {RECOMMENDATION_LABELS[match.recommendation]}
              </Badge>
            </div>
          )}

          <div>
            <p className="text-xs text-muted-foreground">Requirements checked</p>
            <p className="text-sm">
              {match.scored_requirements} of {match.total_requirements}
            </p>
          </div>
        </div>

        {match.score_cap_reason && (
          <p className="text-sm text-muted-foreground">{match.score_cap_reason}</p>
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

function Blockers({ items }: { items: MatchItem[] }) {
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
            <li key={item.id} className="text-sm">
              {item.explanation}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

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
              <span className="tabular-nums text-muted-foreground">{row.score}%</span>
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

function Highlights({
  title,
  description,
  items,
}: {
  title: string;
  description: string;
  items: MatchItem[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-sm">
              <StatusIcon status={item.status} />
              <span>{item.explanation}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Requirements({ items }: { items: MatchItem[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Requirement by requirement</CardTitle>
        <CardDescription>
          Every requirement, its verdict, and the evidence behind it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item) => (
            <RequirementRow key={item.id} item={item} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function RequirementRow({ item }: { item: MatchItem }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <StatusIcon status={item.status} />
          <p className="text-sm">{item.explanation}</p>
        </div>
        <StatusBadge status={item.status} />
      </div>

      {item.evidence.length > 0 ? (
        <>
          <Disclosure
            open={open}
            onToggle={() => setOpen((value) => !value)}
            label="Why this verdict?"
            openLabel="Hide the evidence"
            count={item.evidence.length}
          />

          {open && (
            <ul className="mt-2 space-y-2 border-l-2 pl-3">
              {item.evidence.map((ref) => (
                <li key={ref.id} className="text-xs">
                  <p className="font-medium">{ref.label}</p>
                  {ref.detail && <p className="text-muted-foreground">{ref.detail}</p>}
                  {/* Shown because unverified data must never look like a
                      confirmed fact, even when it is legitimately cited. */}
                  {ref.verification_status !== "USER_CONFIRMED" &&
                    ref.verification_status !== "EVIDENCE_BACKED" && (
                      <p className="text-muted-foreground">Not yet confirmed by you</p>
                    )}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No evidence in your profile for this.</p>
      )}
    </li>
  );
}

const STATUS_ICONS: Record<MatchStatus, typeof CheckCircle2> = {
  STRONG_MATCH: CheckCircle2,
  MATCH: CheckCircle2,
  PARTIAL_MATCH: CircleDashed,
  TRANSFERABLE_MATCH: ArrowLeftRight,
  NO_EVIDENCE: CircleHelp,
  GAP: MinusCircle,
  BLOCKER: AlertOctagon,
  UNKNOWN: CircleHelp,
};

const TONE_CLASSES: Record<string, string> = {
  strong: "text-emerald-600 dark:text-emerald-400",
  ok: "text-amber-600 dark:text-amber-400",
  transfer: "text-purple-600 dark:text-purple-400",
  gap: "text-amber-600 dark:text-amber-400",
  blocked: "text-destructive",
  neutral: "text-muted-foreground",
};

function StatusIcon({ status }: { status: MatchStatus }) {
  const Icon = STATUS_ICONS[status];
  return (
    <Icon
      aria-hidden
      className={`mt-0.5 size-4 shrink-0 ${TONE_CLASSES[MATCH_STATUS_TONE[status]]}`}
    />
  );
}

function StatusBadge({ status }: { status: MatchStatus }) {
  return (
    <Badge variant={isPositiveMatch(status) ? "default" : "outline"}>
      {MATCH_STATUS_LABELS[status]}
    </Badge>
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
          ? "rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm"
          : "rounded-md border p-3 text-sm text-muted-foreground"
      }
    >
      {children}
    </div>
  );
}
