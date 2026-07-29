"use client";

import {
  EMPLOYMENT_TYPE_LABELS,
  IMPORT_METHOD_LABELS,
  SENIORITY_LABELS,
  WORK_MODE_LABELS,
  type Job,
} from "@jip/shared-types";
import { Archive, ArchiveRestore, ExternalLink, Loader2, RotateCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useDeleteJob,
  useJob,
  useJobAction,
  useJobSource,
  useSupplyDescription,
} from "@/features/jobs/api";
import { JobIntelligence } from "@/features/jobs/job-intelligence";
import { JobMatchPanel } from "@/features/jobs/job-match";
import { ImportMethodBadge, JobStatusBadge } from "@/features/jobs/job-status-badge";
import { JobTailoringPanel } from "@/features/resumes/job-tailoring";
import { ApiError } from "@/lib/api";

/**
 * The job detail screen.
 *
 * Two halves, deliberately separated. This component renders the posting and
 * what the user typed; `JobIntelligence` renders the analysis of it, in its own
 * panel with its own language. `docs/08-ui-ux.md` requires AI output to be
 * visibly distinct from fact, and the cleanest way to keep that true is for the
 * two never to share a card.
 *
 * Still absent: application data. It does not exist, and rendering an empty
 * version would look like a broken feature rather than an unbuilt one.
 */
export function JobDetail({ jobId }: { jobId: string }) {
  const job = useJob(jobId);

  if (job.isPending) {
    return <Notice>Loading this job…</Notice>;
  }

  if (job.isError || !job.data) {
    const missing = job.error instanceof ApiError && job.error.status === 404;
    return (
      <Notice tone="error">
        {missing ? "That job does not exist, or is not yours." : "Could not load this job."}
      </Notice>
    );
  }

  return <JobView job={job.data} />;
}

function JobView({ job }: { job: Job }) {
  const router = useRouter();
  const archive = useJobAction(job.id, job.archived_at ? "unarchive" : "archive");
  const remove = useDeleteJob();

  const facts: Array<[string, string]> = [
    ["Company", job.company ?? "—"],
    ["Location", job.location ?? "—"],
    ["Work mode", job.work_mode ? WORK_MODE_LABELS[job.work_mode] : "—"],
    ["Employment type", job.employment_type ? EMPLOYMENT_TYPE_LABELS[job.employment_type] : "—"],
    ["Seniority", job.seniority ? SENIORITY_LABELS[job.seniority] : "—"],
    ["Salary", job.salary_text ?? "—"],
  ];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <Link
          href="/jobs"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          ← Jobs
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{job.title}</h1>
            {job.company && <p className="text-muted-foreground">{job.company}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} />
            {job.archived_at && <Badge variant="outline">Archived</Badge>}
            <ImportMethodBadge method={job.import_method} />
          </div>
        </div>
      </header>

      {job.status === "FETCHING" && <FetchingNotice />}
      {job.status === "FAILED" && <FailedNotice job={job} />}

      {/* The analysis sits above the raw details on purpose: once a posting has
          been read, the structured version is what someone deciding about the
          job actually wants, and the description below is what they check it
          against. */}
      {job.status !== "FETCHING" && job.status !== "FAILED" && (
        <>
          <JobIntelligence job={job} />
          {/* Below the analysis, because a match only means something once
              the posting has been read into requirements. */}
          <JobMatchPanel job={job} />
          {/* Last, and in that order deliberately: the resume strategy is
              built from the match, so seeing it above the score would invite
              tailoring towards a job before knowing whether it fits. */}
          <JobTailoringPanel job={job} />
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Details</CardTitle>
          <CardDescription>What you entered, or what the posting said.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-sm">{value}</dd>
              </div>
            ))}
          </dl>

          {job.source_url && (
            <p className="mt-4 text-sm">
              <a
                href={job.source_url}
                target="_blank"
                // noreferrer as well as noopener: the target is a URL the user
                // supplied, and there is no reason to hand it our page address.
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 underline underline-offset-4"
              >
                Open the original posting
                <ExternalLink aria-hidden className="size-3.5" />
              </a>
            </p>
          )}
        </CardContent>
      </Card>

      {job.description && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Description</CardTitle>
          </CardHeader>
          <CardContent>
            {/* whitespace-pre-wrap, not a markdown renderer: this is text from
                an untrusted page, and rendering it as markup would be handing
                a job posting a script tag on our origin. */}
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{job.description}</p>
          </CardContent>
        </Card>
      )}

      {job.notes && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{job.notes}</p>
          </CardContent>
        </Card>
      )}

      <SourcePanel jobId={job.id} />

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-6">
          <Button
            type="button"
            variant="secondary"
            disabled={archive.isPending}
            onClick={() => archive.mutate()}
          >
            {job.archived_at ? (
              <>
                <ArchiveRestore aria-hidden className="size-4" />
                Bring back
              </>
            ) : (
              <>
                <Archive aria-hidden className="size-4" />
                Archive
              </>
            )}
          </Button>

          <Button
            type="button"
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => remove.mutate(job.id, { onSuccess: () => router.push("/jobs") })}
          >
            <Trash2 aria-hidden className="size-4" />
            Delete permanently
          </Button>

          <p className="text-xs text-muted-foreground">
            Archiving keeps the job and its posting. Deleting does not.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function FetchingNotice() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <Loader2 aria-hidden className="size-4 animate-spin" />
        <p className="text-sm" aria-live="polite">
          Reading the posting. This page updates on its own when it finishes.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * The manual fallback.
 *
 * `GOAL.md` requires a failed fetch to leave the job usable, and the user has
 * to be told that or they will start over. The paste box is right here rather
 * than behind a link for the same reason.
 */
function FailedNotice({ job }: { job: Job }) {
  const supply = useSupplyDescription(job.id);
  const retry = useJobAction(job.id, "retry-import");
  const [text, setText] = useState("");

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-base">We could not read that page</CardTitle>
        <CardDescription>
          {job.fetch_error ?? "The page could not be reached."} Your job is saved, and the link is
          still here — paste the description and you are done.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="fallback-description">Job description</Label>
          <Textarea
            id="fallback-description"
            className="min-h-40"
            placeholder="Paste the description from the posting."
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            disabled={!text.trim() || supply.isPending}
            onClick={() => supply.mutate(text.trim())}
          >
            {supply.isPending ? "Saving…" : "Save description"}
          </Button>

          {job.source_url && (
            <Button
              type="button"
              variant="outline"
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            >
              <RotateCw aria-hidden className="size-4" />
              {retry.isPending ? "Trying…" : "Try the link again"}
            </Button>
          )}

          <p aria-live="polite" className="text-sm text-destructive">
            {(supply.isError || retry.isError) && "That did not work. Try again in a moment."}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The preserved original, behind a disclosure.
 *
 * Fetched only when opened: the raw HTML of a job page is large and almost
 * never looked at. That it exists at all is the point — the posting will be
 * taken down, and this is the record of what it said.
 */
function SourcePanel({ jobId }: { jobId: string }) {
  const [open, setOpen] = useState(false);
  const source = useJobSource(jobId, open);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Original source</CardTitle>
        <CardDescription>
          Exactly what arrived, kept unchanged. Editing this job never alters it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide" : "Show"} the original
        </Button>

        {open && source.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
        {open && source.isError && (
          <p className="text-sm text-destructive">Could not load the original.</p>
        )}

        {open && source.data && (
          <div className="space-y-3">
            <dl className="grid gap-3 text-xs sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">Imported as</dt>
                <dd>{IMPORT_METHOD_LABELS[source.data.import_method]}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Attempts</dt>
                <dd>{source.data.imports.length}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">First imported</dt>
                <dd>{formatTimestamp(source.data.imports[0]?.imported_at ?? null)}</dd>
              </div>
            </dl>

            {source.data.original_description ? (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">
                {source.data.original_description}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground">
                Nothing was captured for this job — it was typed in by hand.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString();
}

function Notice({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
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
