"use client";

import {
  EMPLOYMENT_TYPE_LABELS,
  SENIORITY_LABELS,
  WORK_MODE_LABELS,
  type JobListQuery,
  type JobSummary,
  type MatchStatus,
  type AlignmentDistribution,
} from "@jip/shared-types";
import {
  AlertTriangle,
  Archive,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Plus,
  Radar,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton, SkeletonRegion } from "@/components/ui/skeleton";
import { StateCard } from "@/components/ui/state-card";
import { useBulkArchive, useCompanies, useJobDistribution, useJobs } from "@/features/jobs/api";
import { JobFilters } from "@/features/jobs/job-filters";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SavedViews } from "@/features/jobs/saved-views";

/** Matches `DEFAULT_PAGE_SIZE` in `application/jobs/queries.py`. */
const DEFAULT_PAGE_SIZE = 20;

const INITIAL: JobListQuery = {
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
  sort: "NEWEST",
  archived: "ACTIVE",
};

export function JobsList() {
  const [query, setQuery] = useState<JobListQuery>(INITIAL);
  const jobs = useJobs(query);
  const companies = useCompanies();
  const distribution = useJobDistribution(query);

  const update = (next: Partial<JobListQuery>) => setQuery((current) => ({ ...current, ...next }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-muted-foreground">
            Every role you are considering, kept with the posting it came from.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Discovery sits beside "Add job" rather than in the main navigation,
            because it is the other answer to the same question — where the next
            job comes from. It stays out of the nav until Phase 12 closes, since
            `destinations.ts` derives what is available from the shipped phase
            and claiming this one had shipped would be false. */}
          <Button asChild variant="secondary">
            <Link href="/discovery">
              <Radar aria-hidden className="size-4" />
              Discover
            </Link>
          </Button>
          <Button asChild>
            <Link href="/jobs/new">
              <Plus aria-hidden className="size-4" />
              Add job
            </Link>
          </Button>
        </div>
      </div>

      <JobFilters
        query={query}
        companies={companies.data ?? []}
        onChange={update}
        onReset={() => setQuery(INITIAL)}
      />

      {/* Applying a view replaces the query rather than merging into it. A
          merge would leave whatever the reader had set before sitting
          underneath a name that does not mention it, which is the one thing a
          named place must not do. Page one, for the reason the band filter
          gives: a different set, read from the start. */}
      <SavedViews
        query={query}
        onApply={(filters) => setQuery({ ...INITIAL, ...filters, page: 1 })}
      />

      {distribution.data && (
        <Distribution
          data={distribution.data}
          active={{ min: query.min_score, max: query.max_score }}
          // Back to page one: a band is a different set, and staying on page
          // three of the old one lands the reader somewhere empty.
          onSelectBand={(band) => update({ ...band, page: 1 })}
        />
      )}

      <JobResults query={query} jobs={jobs} onPage={(page) => update({ page })} />
    </div>
  );
}

function JobResults({
  query,
  jobs,
  onPage,
}: {
  query: JobListQuery;
  jobs: ReturnType<typeof useJobs>;
  onPage: (page: number) => void;
}) {
  // Cleared whenever the visible set changes: a selection is a statement about
  // rows on screen, and carrying it across a filter or a page would archive
  // something the reader can no longer see.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<BulkArchiveOutcome | null>(null);
  const archive = useBulkArchive();

  useEffect(() => {
    setSelected(new Set());
  }, [query]);

  const select = (id: string, next: boolean) =>
    setSelected((current) => {
      const updated = new Set(current);
      if (next) updated.add(id);
      else updated.delete(id);
      return updated;
    });

  if (jobs.isPending) {
    return <JobRowsSkeleton rows={query.page_size ?? DEFAULT_PAGE_SIZE} />;
  }

  if (jobs.isError) {
    return (
      <StateCard tone="error">
        {jobs.error instanceof ApiError && jobs.error.isUnauthenticated
          ? "Your session was not accepted. Try signing out and back in."
          : "Could not load your jobs."}
      </StateCard>
    );
  }

  const { data: rows, meta } = jobs.data;

  if (rows.length === 0) {
    return <EmptyState filtered={hasFilters(query)} />;
  }

  const chosen = rows.filter((job) => selected.has(job.id));

  const runArchive = () => {
    const ids = chosen.map((job) => job.id);
    const titles = new Map(chosen.map((job) => [job.id, job.title]));
    archive.mutate(ids, {
      onSuccess: (outcome) => {
        setResult({
          archived: outcome.archived.length,
          missing: outcome.missing.map((id) => titles.get(id) ?? "a job that is no longer there"),
        });
        setSelected(new Set());
      },
    });
  };

  return (
    <div className="space-y-4">
      {chosen.length > 0 && (
        <SelectionBar
          count={chosen.length}
          pending={archive.isPending}
          onArchive={runArchive}
          onClear={() => setSelected(new Set())}
        />
      )}

      {result && <ArchiveOutcome result={result} onDismiss={() => setResult(null)} />}

      <JobRows rows={rows} selected={selected} onSelect={select} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {meta.total} {meta.total === 1 ? "job" : "jobs"}
          {meta.total_pages > 1 && ` · page ${meta.page} of ${meta.total_pages}`}
        </p>

        {meta.total_pages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={meta.page <= 1}
              onClick={() => onPage(meta.page - 1)}
            >
              <ChevronLeft aria-hidden className="size-4" />
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={meta.page >= meta.total_pages}
              onClick={() => onPage(meta.page + 1)}
            >
              Next
              <ChevronRight aria-hidden className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/*
 * A pair, and they are only correct together.
 *
 * The checkbox cannot sit inside the link — a control nested in an anchor is
 * both invalid and unusable, since every click would navigate. So the row is an
 * outer grid holding the checkbox and the link, and the link is an inner grid
 * holding the five columns. Two constants rather than one because there are two
 * grids; declared adjacent because the header, the rows and the skeleton all
 * use both, and a header that stops naming the column beneath it is the defect
 * this guards against.
 */
const ROW_OUTER = "grid grid-cols-[24px_1fr] items-center gap-3.5 px-3.5";
const ROW_INNER = "grid grid-cols-[1fr_180px_92px_150px_52px] items-center gap-3.5";

type BulkArchiveOutcome = { archived: number; missing: string[] };

/**
 * The shape of the whole set, and the way into a part of it.
 *
 * At twenty-four jobs a reader can scan the list. At two hundred they cannot,
 * and the useful question stops being "what is on this page" and becomes "how
 * many are worth opening at all" — which no amount of paging answers. So the
 * figure is a distribution across everything the filters match, and each band
 * is a control that narrows to it.
 *
 * Unscored jobs sit apart from the bands, for the reason the API keeps them
 * apart: a job nobody matched has not scored badly, and a bar that swept it
 * into the lowest band would be a verdict on work that was never done.
 *
 * The counts are the label rather than a tooltip. A bar whose value only
 * appears on hover has no value on a touch screen, and `docs/08-ui-ux.md` wants
 * a chart readable without a pointer.
 */
function Distribution({
  data,
  active,
  onSelectBand,
}: {
  data: AlignmentDistribution;
  active: { min?: number; max?: number };
  onSelectBand: (band: { min_score?: number; max_score?: number }) => void;
}) {
  if (data.total === 0) return null;

  const widest = Math.max(...data.buckets.map((b) => b.count), data.unscored, 1);

  return (
    <div className="space-y-2 rounded-xl border p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">How these {data.total} jobs line up</h2>
        {(active.min !== undefined || active.max !== undefined) && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onSelectBand({ min_score: undefined, max_score: undefined })}
          >
            Show every band
          </Button>
        )}
      </div>

      <ul className="space-y-1">
        {data.buckets.map((bucket, index) => {
          // Bands are ordered high to low and are closed ranges, so a band's
          // ceiling is one below the floor of the band above it.
          const above = data.buckets[index - 1];
          const ceiling = above === undefined ? 100 : above.floor - 1;
          const selected = active.min === bucket.floor && active.max === ceiling;

          return (
            <li key={bucket.floor}>
              <button
                type="button"
                aria-pressed={selected}
                disabled={bucket.count === 0}
                onClick={() =>
                  onSelectBand(
                    selected
                      ? { min_score: undefined, max_score: undefined }
                      : { min_score: bucket.floor, max_score: ceiling },
                  )
                }
                className={cn(
                  "grid w-full grid-cols-[136px_1fr_2.5rem] items-center gap-3 rounded px-2 py-1 text-left text-xs",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  bucket.count === 0
                    ? "cursor-default text-muted-foreground/60"
                    : "hover:bg-muted/60",
                  selected && "bg-muted",
                )}
              >
                <span className="truncate">{bucket.label}</span>
                <span aria-hidden className="flex h-2 overflow-hidden rounded-full bg-muted">
                  <span
                    className={cn("rounded-full", selected ? "bg-primary" : "bg-primary/50")}
                    style={{ width: `${(bucket.count / widest) * 100}%` }}
                  />
                </span>
                <span className="text-right font-mono tabular-nums">{bucket.count}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {data.unscored > 0 && (
        <p className="border-t pt-2 text-xs text-muted-foreground">
          <span className="font-mono tabular-nums text-foreground">{data.unscored}</span> not
          compared against your profile yet, so they have no figure — not a low one.
        </p>
      )}
    </div>
  );
}

/** What is selected, and the one thing that can be done with it. */
function SelectionBar({
  count,
  pending,
  onArchive,
  onClear,
}: {
  count: number;
  pending: boolean;
  onArchive: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/40 px-4 py-2.5">
      <p className="text-sm font-medium" aria-live="polite">
        {count} selected
      </p>
      <div className="ml-auto flex items-center gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        <Button type="button" size="sm" disabled={pending} onClick={onArchive}>
          <Archive aria-hidden className="size-4" />
          {pending ? "Archiving…" : `Archive ${count}`}
        </Button>
      </div>
    </div>
  );
}

/**
 * What happened, and it stays until dismissed.
 *
 * Not a toast. The outcome of an action on twenty-nine rows is not something a
 * reader should have five seconds to catch, and a message that disappears on
 * its own is one they can miss entirely. It also has to be able to name what it
 * could not do: the call is not atomic, so a partial result is the ordinary
 * outcome rather than an error, and "27 archived" with no way to see which two
 * failed would send someone back to reselect thirty rows.
 *
 * No undo, because none is needed — archiving is reversible through the
 * Archived view, unlike deleting.
 */
function ArchiveOutcome({
  result,
  onDismiss,
}: {
  result: BulkArchiveOutcome;
  onDismiss: () => void;
}) {
  return (
    <Callout tone={result.missing.length > 0 ? "caution" : "note"} role="status">
      <div className="flex items-start gap-3">
        <div className="space-y-1">
          <p className="font-medium text-foreground">
            {result.archived} {result.archived === 1 ? "job" : "jobs"} archived. They are still in
            your list under Archived.
          </p>
          {result.missing.length > 0 && (
            <p>
              {result.missing.length} could not be archived and{" "}
              {result.missing.length === 1 ? "is" : "are"} still here: {result.missing.join(", ")}.
            </p>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto shrink-0"
          onClick={onDismiss}
        >
          Dismiss
        </Button>
      </div>
    </Callout>
  );
}

function JobRows({
  rows,
  selected,
  onSelect,
}: {
  rows: JobSummary[];
  selected: Set<string>;
  onSelect: (id: string, next: boolean) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border">
      {/* Visual only: every column's content is inside the link's own text, so
          announcing these again would read each row twice. */}
      <div
        aria-hidden
        className={cn(
          ROW_OUTER,
          "h-9 border-b bg-muted/40 text-xs font-medium uppercase tracking-wider text-muted-foreground",
        )}
      >
        <span />
        <span className={ROW_INNER}>
          <span>Role</span>
          <span>Company and place</span>
          <span>Coverage</span>
          <span>Alignment</span>
          <span className="text-right">Figure</span>
        </span>
      </div>

      <ul>
        {rows.map((job) => (
          <JobRow key={job.id} job={job} selected={selected.has(job.id)} onSelect={onSelect} />
        ))}
      </ul>
    </div>
  );
}

function JobRowsSkeleton({ rows }: { rows: number }) {
  return (
    <SkeletonRegion label="Loading your jobs…">
      <div className="overflow-hidden rounded-xl border">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className={cn(ROW_OUTER, "h-11 border-b last:border-b-0")}>
            <Skeleton className="size-4 rounded" />
            <div className={ROW_INNER}>
              <Skeleton className="h-4 w-2/5" />
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-1 w-full" />
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="ml-auto h-4 w-7" />
            </div>
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/**
 * The order the coverage strip reads in: best evidence first, absence last.
 *
 * `MATCH` and `STRONG_MATCH` share a token because the strip is four pixels
 * tall and answers "how much of this is covered", not "how well". The verdict
 * that a requirement got is the job screen's answer, at a size that can carry
 * the distinction.
 */
const STRIP_BANDS: { keys: MatchStatus[]; className: string }[] = [
  { keys: ["STRONG_MATCH", "MATCH"], className: "bg-verdict-strong" },
  { keys: ["PARTIAL_MATCH"], className: "bg-verdict-partial" },
  { keys: ["TRANSFERABLE_MATCH"], className: "bg-verdict-transfer" },
  { keys: ["GAP", "NO_EVIDENCE"], className: "bg-verdict-gap" },
  { keys: ["BLOCKER"], className: "bg-verdict-blocked" },
];

/**
 * Coverage at row scale.
 *
 * `aria-hidden`, with the same fact written out beside it in the row's own
 * text. A four-pixel band carries its meaning in hue alone, which
 * `docs/08-ui-ux.md` forbids as the *only* carrier — so it is the summary a
 * sighted reader scans, and never the thing that has to be read.
 *
 * `UNKNOWN` is deliberately not a band. A requirement nobody could assess from
 * a profile is not covered and is not a gap, and painting it as either would
 * make the strip claim something the matcher declined to.
 */
function CoverageStrip({ job }: { job: JobSummary }) {
  // Defaulted rather than assumed. The payload sends `{}` and `0`, but a
  // response cached before those fields existed would otherwise throw here and
  // take the whole row with it.
  const counts = job.status_counts ?? {};
  const total = job.total_requirements ?? 0;
  if (total <= 0) return <span aria-hidden />;

  return (
    <span aria-hidden className="flex h-1 gap-px overflow-hidden rounded-full bg-muted">
      {STRIP_BANDS.map((band) => {
        const count = band.keys.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
        if (count === 0) return null;
        return (
          <span
            key={band.className}
            className={band.className}
            style={{ width: `${(count / total) * 100}%` }}
          />
        );
      })}
    </span>
  );
}

/** How many requirements the profile answered, for the row's accessible text. */
function coveredCount(job: JobSummary): number {
  const counts = job.status_counts ?? {};
  const counted: MatchStatus[] = ["STRONG_MATCH", "MATCH", "PARTIAL_MATCH", "TRANSFERABLE_MATCH"];
  return counted.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
}

/**
 * Where this job is, in one column.
 *
 * The design removed the badges from the dense row because the conditional
 * "Archived" one was pushing the figure out of its column. The grid fixes that
 * by construction, so what is left is a question of meaning rather than
 * alignment: a row says either how it scored or why it has not, and both are
 * the same column because a reader scanning for "what needs me" looks in one
 * place.
 *
 * Processing state wins when there is one. `JobStatusBadge` renders nothing for
 * the two resting states, which is what makes this safe — a badge on every row
 * would be the noise `docs/08-ui-ux.md` asks us to avoid, and the states that
 * do render are exactly the ones a user has to act on.
 *
 * Set as text rather than as a pill: at a 44px row a badge's own padding costs
 * more than the words are worth, and the icon still carries the meaning beside
 * the colour.
 */
function JobStateCell({ job }: { job: JobSummary }) {
  if (job.status === "FETCHING" || job.status === "PARSING" || job.status === "ANALYZING") {
    return (
      <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
        <Loader2 aria-hidden className="size-3 shrink-0 animate-spin" />
        {job.status === "FETCHING" ? "Reading the page" : "Analysing"}
      </span>
    );
  }

  if (job.status === "FAILED" || job.status === "ANALYSIS_FAILED") {
    return (
      <span className="flex items-center gap-1.5 truncate text-xs text-destructive">
        <AlertTriangle aria-hidden className="size-3 shrink-0" />
        {job.status === "FAILED" ? "Needs a description" : "Analysis failed"}
      </span>
    );
  }

  return (
    <span className="truncate text-xs text-muted-foreground">
      {job.alignment_label ?? "Not yet analysed"}
      {job.is_stale && " · out of date"}
    </span>
  );
}

function JobRow({
  job,
  selected,
  onSelect,
}: {
  job: JobSummary;
  selected: boolean;
  onSelect: (id: string, next: boolean) => void;
}) {
  const facts = [
    job.company,
    job.location,
    job.work_mode ? WORK_MODE_LABELS[job.work_mode] : null,
    job.employment_type ? EMPLOYMENT_TYPE_LABELS[job.employment_type] : null,
    job.seniority ? SENIORITY_LABELS[job.seniority] : null,
  ].filter(Boolean);

  const scored = job.score !== null;

  return (
    <li className={cn(ROW_OUTER, "h-11 border-b last:border-b-0", selected && "bg-muted/60")}>
      {/*
        A real checkbox, outside the link.

        Nesting a control inside an anchor is invalid and unusable — every click
        would navigate — so the row is two cells and only the second is the
        link. The accessible name is the job's title rather than "select",
        because a screen reader moving down the column hears the checkboxes and
        nothing else, and "select, select, select" names nothing.
      */}
      <input
        type="checkbox"
        checked={selected}
        onChange={(event) => onSelect(job.id, event.target.checked)}
        aria-label={`Select ${job.title}`}
        className="size-4 cursor-pointer rounded border-input accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />

      <Link
        href={`/jobs/${job.id}`}
        className={cn(
          ROW_INNER,
          "h-full items-center transition-colors hover:bg-muted/50",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
        )}
      >
        <span className="truncate text-sm font-medium">{job.title}</span>

        <span className="truncate text-xs text-muted-foreground">{facts.join(" · ")}</span>

        <CoverageStrip job={job} />

        <JobStateCell job={job} />

        {/*
          The figure, and the dash that is not a zero.

          `tabular-nums` because the whole reason this became a column is that a
          reader compares it down the page, and proportional digits make 78 and
          100 start in different places.
        */}
        <span className="text-right font-mono text-lg font-medium tabular-nums">
          {scored ? job.score : <span className="text-muted-foreground">—</span>}
        </span>

        {/* What the strip means, for a reader who cannot see it. */}
        <span className="sr-only">
          {scored
            ? `${coveredCount(job)} of ${job.total_requirements} requirements answered by your profile`
            : "No match computed yet"}
        </span>
      </Link>
    </li>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  // Two different situations that look identical if the copy does not
  // distinguish them: nothing saved yet, versus nothing matching. Telling a
  // user with forty jobs that they have none would read as data loss.
  if (filtered) {
    return <StateCard>No jobs match those filters. Try widening them.</StateCard>;
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-8 text-center">
        <p className="text-sm font-medium">Add your first job to start building the picture.</p>
        <p className="text-sm text-muted-foreground">
          Paste a description, drop in a link, or type the details yourself. We keep the original
          posting so it is still here after the listing comes down.
        </p>
        <Button asChild>
          <Link href="/jobs/new">
            <Plus aria-hidden className="size-4" />
            Add a job
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function hasFilters(query: JobListQuery): boolean {
  return Boolean(
    query.search ||
    query.company ||
    query.work_mode ||
    query.employment_type ||
    query.seniority ||
    query.min_score !== undefined ||
    (query.archived && query.archived !== "ACTIVE"),
  );
}
