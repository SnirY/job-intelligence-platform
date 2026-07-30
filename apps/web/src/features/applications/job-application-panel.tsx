"use client";

import {
  APPLICATION_SOURCE_LABELS,
  APPLICATION_STATUS_LABELS,
  type Application,
  type ApplicationSource,
  type ApplicationStatus,
  type Job,
} from "@jip/shared-types";
import { Send } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useApplications,
  useChangeStatus,
  useCreateApplication,
  useMarkApplied,
} from "@/features/applications/api";
import { useResumes, useVersions } from "@/features/resumes/api";
import { ApiError } from "@/lib/api";

/**
 * Tracking, from the job it belongs to.
 *
 * The application is created here rather than on the tracker, because this is
 * where the user decides they are actually pursuing something. It is
 * deliberately an explicit act: a job saved and never looked at again is not a
 * relationship with an opportunity, and auto-creating one would make
 * "applications" a synonym for "jobs".
 */
export function JobApplicationPanel({ job }: { job: Job }) {
  const applications = useApplications(true);
  const create = useCreateApplication();

  if (applications.isPending) return null;

  const existing = applications.data?.find((row) => row.job_id === job.id);

  if (!existing) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm font-medium">Not tracking this one yet.</p>
          <p className="text-sm text-muted-foreground">
            Start tracking when you decide to pursue it. Everything after that — what stage it is
            at, which resume you sent, what they said — is kept as it happened.
          </p>
          <Button
            type="button"
            disabled={create.isPending}
            onClick={() => create.mutate({ job_id: job.id })}
          >
            <Send aria-hidden className="size-4" />
            {create.isPending ? "Starting…" : "Track this application"}
          </Button>
          {create.isError && (
            <p className="text-sm text-destructive">
              {create.error instanceof ApiError
                ? create.error.message
                : "Could not start tracking this job."}
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  return <TrackedApplication application={existing} />;
}

function TrackedApplication({ application }: { application: Application }) {
  const change = useChangeStatus();

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">Application</CardTitle>
          <CardDescription>
            {application.applied_at
              ? `Sent ${new Date(application.applied_at).toLocaleDateString()}`
              : "Not sent yet."}
          </CardDescription>
        </div>
        <Badge>{APPLICATION_STATUS_LABELS[application.status]}</Badge>
      </CardHeader>

      <CardContent className="space-y-4">
        {application.allowed_transitions.length > 0 && (
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="app-status">Move to</Label>
              <Select
                id="app-status"
                className="w-56"
                value=""
                disabled={change.isPending}
                onChange={(event) => {
                  const next = event.target.value as ApplicationStatus;
                  if (next) change.mutate({ id: application.id, status: next });
                }}
              >
                <option value="">Choose a stage…</option>
                {application.allowed_transitions.map((status) => (
                  <option key={status} value={status}>
                    {APPLICATION_STATUS_LABELS[status]}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        )}

        {change.isError && (
          <p className="text-sm text-destructive">
            {change.error instanceof ApiError ? change.error.message : "That move was refused."}
          </p>
        )}

        {!application.applied_at && <MarkApplied application={application} />}

        <p className="text-sm">
          <Link href="/applications" className="underline underline-offset-4">
            Open the tracker
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * The moment `docs/07` cares most about.
 *
 * Four things are preserved: the date, the exact resume version, the source,
 * and any note. The version is also frozen — from here it is what an employer
 * read, and editing it would rewrite what was sent.
 */
function MarkApplied({ application }: { application: Application }) {
  const resumes = useResumes();
  const [resumeId, setResumeId] = useState("");
  const versions = useVersions(resumeId);
  const [versionId, setVersionId] = useState("");
  const [source, setSource] = useState<ApplicationSource | "">("");
  const [appliedAt, setAppliedAt] = useState("");
  const apply = useMarkApplied(application.id);

  return (
    <div className="space-y-3 border-t pt-4">
      <p className="text-sm font-medium">Mark as sent</p>
      <p className="text-sm text-muted-foreground">
        The version you attach is locked afterwards. An application record has to describe the
        document that was actually sent.
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="apply-resume">Resume</Label>
          <Select
            id="apply-resume"
            value={resumeId}
            onChange={(event) => {
              setResumeId(event.target.value);
              setVersionId("");
            }}
          >
            <option value="">Not recorded</option>
            {(resumes.data ?? []).map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.title}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="apply-version">Version</Label>
          <Select
            id="apply-version"
            value={versionId}
            disabled={!resumeId}
            onChange={(event) => setVersionId(event.target.value)}
          >
            <option value="">Choose a version…</option>
            {(versions.data ?? []).map((version) => (
              <option key={version.id} value={version.id}>
                v{version.version}
                {version.label ? ` — ${version.label}` : ""}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="apply-source">Where</Label>
          <Select
            id="apply-source"
            value={source}
            onChange={(event) => setSource(event.target.value as ApplicationSource | "")}
          >
            <option value="">Not recorded</option>
            {Object.entries(APPLICATION_SOURCE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="apply-date">Date sent</Label>
          {/* Supplied rather than assumed: someone recording last month's
              applications needs the timeline to read correctly. */}
          <Input
            id="apply-date"
            type="date"
            value={appliedAt}
            onChange={(event) => setAppliedAt(event.target.value)}
          />
        </div>
      </div>

      <Button
        type="button"
        disabled={apply.isPending}
        onClick={() =>
          apply.mutate({
            resume_version_id: versionId || null,
            source: source || null,
            applied_at: appliedAt ? new Date(appliedAt).toISOString() : null,
          })
        }
      >
        <Send aria-hidden className="size-4" />
        {apply.isPending ? "Recording…" : "Mark as sent"}
      </Button>

      {apply.isError && (
        <p className="text-sm text-destructive">
          {apply.error instanceof ApiError ? apply.error.message : "Could not record that."}
        </p>
      )}
    </div>
  );
}
