"use client";

import {
  APPLICATION_SOURCE_LABELS,
  APPLICATION_STATUS_LABELS,
  type Application,
  type ApplicationSource,
  type Job,
} from "@jip/shared-types";
import { Send } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

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
import { useResumes, useVersion, useVersions } from "@/features/resumes/api";
import { ApiError } from "@/lib/api";
import type { ResumeVersionDetail } from "@jip/shared-types";

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
        {/*
          Buttons rather than a select, and the reason is what the select did to
          a keyboard.

          It held `value=""` and moved the application on `change`. Two things
          followed. It never showed where the application actually was — the
          control that moves you somewhere also has to say where you are. And
          arrow-keying through it fires `change` per option in a native select,
          so a reader walking from "HR screen" down to "Offer" would post every
          stage on the way. Application status is append-only and every move
          writes an event, so that is not a wasted request: it is a career
          history that says things which never happened, written by somebody who
          was only looking.

          One button, one deliberate move. `allowed_transitions` comes from the
          server's own transition table, so the offer and the refusal cannot
          disagree.
        */}
        <div className="space-y-2">
          <p id="stage-now" className="text-sm">
            <span className="text-muted-foreground">Now at</span>{" "}
            <span className="font-medium">{APPLICATION_STATUS_LABELS[application.status]}</span>
          </p>

          {application.allowed_transitions.length > 0 ? (
            <div role="group" aria-labelledby="stage-now" className="flex flex-wrap gap-2">
              {application.allowed_transitions.map((status) => (
                <Button
                  key={status}
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={change.isPending}
                  onClick={() => change.mutate({ id: application.id, status })}
                >
                  {APPLICATION_STATUS_LABELS[status]}
                </Button>
              ))}
            </div>
          ) : (
            /* A terminal stage. Said out loud rather than left as an absence,
               because a row of buttons that simply stops appearing reads as a
               screen that failed to load them. */
            <p className="text-sm text-muted-foreground">
              This application has nowhere further to go.
            </p>
          )}
        </div>

        {application.applied_at && <SentRecord application={application} />}

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
/**
 * What was actually sent, and with what.
 *
 * `docs/07-applications.md` names four things to preserve when a user applies:
 * the applied date, the exact resume version, the application source, and any
 * notes. The card kept the first and dropped the rest — `resume_version_id` and
 * `source` were collected by the form on the way in and then never shown again.
 *
 * That is the difference between recording something and remembering it. The
 * version matters most, because it is the one fact here that decays: a resume
 * is edited after it is sent, so within a week "which one did they actually
 * see" stops being answerable from the current document.
 *
 * One request, and only for an application that has been sent — `useVersion`
 * is disabled without an id. Not free, and worth it: this is the line the
 * screen exists to still be able to answer in three months.
 */
function SentRecord({ application }: { application: Application }) {
  const version = useVersion(application.resume_version_id);

  const rows: Array<[string, ReactNode]> = [
    ["Sent", new Date(application.applied_at as string).toLocaleDateString()],
    ["Resume", <SentVersion key="v" application={application} version={version.data} />],
    [
      "Through",
      application.source ? (
        APPLICATION_SOURCE_LABELS[application.source]
      ) : (
        /* Not the same as unknown. The form offers "Not recorded" and somebody
           chose it, which is a fact about the application rather than a gap. */
        <span className="text-muted-foreground">Not recorded</span>
      ),
    ],
  ];

  return (
    <dl className="grid gap-3 rounded-lg border p-3.5 sm:grid-cols-3">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-sm">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function SentVersion({
  application,
  version,
}: {
  application: Application;
  version: ResumeVersionDetail | undefined;
}) {
  if (!application.resume_version_id) {
    return <span className="text-muted-foreground">Not recorded</span>;
  }

  // The id was stored and the lookup has not landed, or failed. Said as a
  // wait rather than as an absence: a blank here would read as "nothing was
  // recorded", which is the opposite of what the row knows.
  if (!version) return <span className="text-muted-foreground">Looking it up…</span>;

  return (
    <span>
      {version.label ? `${version.label} · v${version.version}` : `Version ${version.version}`}
    </span>
  );
}

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
