"use client";

import {
  EMPLOYMENT_TYPE_LABELS,
  SENIORITY_LABELS,
  WORK_MODE_LABELS,
  type JobListQuery,
  type JobSummary,
} from "@jip/shared-types";
import { Archive, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton, SkeletonRegion } from "@/components/ui/skeleton";
import { StateCard } from "@/components/ui/state-card";
import { useCompanies, useJobs } from "@/features/jobs/api";
import { JobFilters } from "@/features/jobs/job-filters";
import { ImportMethodBadge, JobStatusBadge } from "@/features/jobs/job-status-badge";
import { ApiError } from "@/lib/api";

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
        <Button asChild>
          <Link href="/jobs/new">
            <Plus aria-hidden className="size-4" />
            Add job
          </Link>
        </Button>
      </div>

      <JobFilters
        query={query}
        companies={companies.data ?? []}
        onChange={update}
        onReset={() => setQuery(INITIAL)}
      />

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

  return (
    <div className="space-y-4">
      <ul className="space-y-3">
        {rows.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </ul>

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

/**
 * The list while it is still arriving, in the shape it will arrive in.
 *
 * A card reading "Loading your jobs…" is one line tall and the list is not, so
 * the page moved under the reader every time it finished loading.
 *
 * The row count comes from the page size rather than from a number that looked
 * about right. It was five against a page size of twenty, which reserved a
 * quarter of the height that was coming and left the jump it existed to
 * prevent. Deriving it means the two cannot drift apart again.
 *
 * The announcement is separate because the rows are `aria-hidden` — a skeleton
 * describes nothing, and without the label the loading state would be silent
 * for the readers who cannot see it.
 */
function JobRowsSkeleton({ rows }: { rows: number }) {
  return (
    <SkeletonRegion label="Loading your jobs…" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <Card key={i}>
          <CardContent className="flex flex-wrap items-start gap-3 p-4">
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-5 w-16" />
            </div>
          </CardContent>
        </Card>
      ))}
    </SkeletonRegion>
  );
}

function JobRow({ job }: { job: JobSummary }) {
  const facts = [
    job.company,
    job.location,
    job.work_mode ? WORK_MODE_LABELS[job.work_mode] : null,
    job.employment_type ? EMPLOYMENT_TYPE_LABELS[job.employment_type] : null,
    job.seniority ? SENIORITY_LABELS[job.seniority] : null,
  ].filter(Boolean);

  return (
    <li>
      <Card className="transition-colors hover:border-primary/40">
        <CardContent className="flex flex-wrap items-start gap-3 p-4">
          <div className="min-w-0 flex-1">
            <Link
              href={`/jobs/${job.id}`}
              className="text-sm font-medium underline-offset-4 hover:underline"
            >
              {job.title}
            </Link>
            {facts.length > 0 && (
              <p className="truncate text-xs text-muted-foreground">{facts.join(" · ")}</p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} />
            {job.archived_at && (
              <Badge variant="outline" className="gap-1">
                <Archive aria-hidden className="size-3" />
                Archived
              </Badge>
            )}
            <ImportMethodBadge method={job.import_method} />
          </div>
        </CardContent>
      </Card>
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
    (query.archived && query.archived !== "ACTIVE"),
  );
}
