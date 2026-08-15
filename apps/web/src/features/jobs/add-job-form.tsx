"use client";

import {
  DUPLICATE_REASON_LABELS,
  EMPLOYMENT_TYPE_LABELS,
  SENIORITY_LABELS,
  WORK_MODE_LABELS,
  isDuplicateDetails,
  type DuplicateDetails,
  type JobCreate,
  type JobImportMethod,
} from "@jip/shared-types";
import { ClipboardPaste, Link2, Loader2, PencilLine } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldHint, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateJob } from "@/features/jobs/api";
import { ApiError } from "@/lib/api";

const METHODS: Array<{ value: JobImportMethod; label: string; icon: typeof Link2; hint: string }> =
  [
    {
      value: "PASTED_DESCRIPTION",
      label: "Paste the description",
      icon: ClipboardPaste,
      hint: "The most reliable option — it works even for postings behind a login.",
    },
    {
      value: "URL",
      label: "Import from a link",
      icon: Link2,
      hint: "We fetch the page and pull out the description. You can still paste if it does not work.",
    },
    {
      value: "MANUAL",
      label: "Type the details",
      icon: PencilLine,
      hint: "For a role you heard about rather than found written down.",
    },
  ];

const EMPTY: JobCreate = {
  import_method: "PASTED_DESCRIPTION",
  title: "",
  company: "",
  location: "",
  work_mode: null,
  employment_type: null,
  seniority: null,
  description: "",
  source_url: "",
  salary_text: "",
  notes: "",
};

export function AddJobForm() {
  const router = useRouter();
  const create = useCreateJob();
  const [draft, setDraft] = useState<JobCreate>(EMPTY);
  const [duplicate, setDuplicate] = useState<DuplicateDetails | null>(null);

  const method = draft.import_method;
  const update = (next: Partial<JobCreate>) => setDraft((current) => ({ ...current, ...next }));

  function submit(allowDuplicate = false) {
    setDuplicate(null);
    create.mutate(
      {
        ...draft,
        title: draft.title?.trim() || null,
        company: draft.company?.trim() || null,
        location: draft.location?.trim() || null,
        description: draft.description?.trim() || null,
        source_url: draft.source_url?.trim() || null,
        salary_text: draft.salary_text?.trim() || null,
        notes: draft.notes?.trim() || null,
        allow_duplicate: allowDuplicate,
      },
      {
        onSuccess: (job) => router.push(`/jobs/${job.id}`),
        onError: (error) => {
          // A 409 is not a failure to report and forget — it carries the job we
          // think this duplicates, so the user can go and look at it or say
          // "add it anyway".
          if (error instanceof ApiError && error.status === 409) {
            const details = error.details;
            if (isDuplicateDetails(details)) setDuplicate(details);
          }
        },
      },
    );
  }

  const canSubmit =
    method === "URL"
      ? Boolean(draft.source_url?.trim())
      : Boolean(draft.title?.trim()) && (method === "MANUAL" || Boolean(draft.description?.trim()));

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) submit();
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle className="text-base">How do you have this job?</CardTitle>
          <CardDescription>
            Whichever you pick, we keep the original exactly as it arrived.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          {METHODS.map(({ value, label, icon: Icon }) => (
            <Button
              key={value}
              type="button"
              variant={method === value ? "default" : "outline"}
              aria-pressed={method === value}
              className="h-auto justify-start py-3"
              onClick={() => update({ import_method: value })}
            >
              <Icon aria-hidden className="size-4" />
              {label}
            </Button>
          ))}
          <p className="text-xs text-muted-foreground sm:col-span-3">
            {METHODS.find((entry) => entry.value === method)?.hint}
          </p>
        </CardContent>
      </Card>

      {method === "URL" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Link to the posting</CardTitle>
            <CardDescription>
              We only fetch public web pages. If the page needs a login or renders in the browser,
              paste the description instead — we will tell you if that happens.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="job-url">Job URL</Label>
            <Input
              id="job-url"
              type="url"
              inputMode="url"
              placeholder="https://careers.example.com/roles/backend-engineer"
              value={draft.source_url ?? ""}
              onChange={(event) => update({ source_url: event.target.value })}
            />
            <FieldHint>The title and description come from the page. You can edit both.</FieldHint>
          </CardContent>
        </Card>
      )}

      {method !== "URL" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">The role</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="job-title">Title</Label>
                <Input
                  id="job-title"
                  value={draft.title ?? ""}
                  maxLength={300}
                  placeholder="Senior Backend Engineer"
                  onChange={(event) => update({ title: event.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-company">Company</Label>
                <Input
                  id="job-company"
                  value={draft.company ?? ""}
                  maxLength={200}
                  onChange={(event) => update({ company: event.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-location">Location</Label>
                <Input
                  id="job-location"
                  value={draft.location ?? ""}
                  maxLength={200}
                  onChange={(event) => update({ location: event.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-work-mode-input">Work mode</Label>
                <Select
                  id="job-work-mode-input"
                  value={draft.work_mode ?? ""}
                  onChange={(event) =>
                    update({ work_mode: (event.target.value || null) as JobCreate["work_mode"] })
                  }
                >
                  <option value="">Not specified</option>
                  {Object.entries(WORK_MODE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-type-input">Employment type</Label>
                <Select
                  id="job-type-input"
                  value={draft.employment_type ?? ""}
                  onChange={(event) =>
                    update({
                      employment_type: (event.target.value || null) as JobCreate["employment_type"],
                    })
                  }
                >
                  <option value="">Not specified</option>
                  {Object.entries(EMPLOYMENT_TYPE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="job-seniority-input">Seniority</Label>
                <Select
                  id="job-seniority-input"
                  value={draft.seniority ?? ""}
                  onChange={(event) =>
                    update({ seniority: (event.target.value || null) as JobCreate["seniority"] })
                  }
                >
                  <option value="">Not specified</option>
                  {Object.entries(SENIORITY_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
                {/* Typed by the user, not inferred. Phase 5 reads the
                    description and records its own answer separately. */}
                <FieldHint>Your read on it, not ours.</FieldHint>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="job-description">
                Description{method === "MANUAL" ? " (optional)" : ""}
              </Label>
              <Textarea
                id="job-description"
                className="min-h-48"
                placeholder="Paste the full job description here."
                value={draft.description ?? ""}
                onChange={(event) => update({ description: event.target.value })}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {duplicate && <DuplicateNotice details={duplicate} onCreateAnyway={() => submit(true)} />}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!canSubmit || create.isPending}>
          {create.isPending && <Loader2 aria-hidden className="size-4 animate-spin" />}
          {create.isPending ? "Saving…" : "Save job"}
        </Button>
        <Button asChild type="button" variant="ghost">
          <Link href="/jobs">Cancel</Link>
        </Button>

        <p aria-live="polite" className="text-sm text-destructive">
          {create.isError && !duplicate && errorMessage(create.error)}
        </p>
      </div>
    </form>
  );
}

function DuplicateNotice({
  details,
  onCreateAnyway,
}: {
  details: DuplicateDetails;
  onCreateAnyway: () => void;
}) {
  return (
    <Card className="border-notice/50">
      <CardHeader>
        <CardTitle className="text-base">You may already have this job</CardTitle>
        <CardDescription>
          {/* Named, not just refused: a bare "duplicate" would leave the user
              unable to find the job they supposedly already have. */}
          <Link
            href={`/jobs/${details.existing_job_id}`}
            className="font-medium underline underline-offset-4"
          >
            {details.existing_title}
          </Link>{" "}
          has {DUPLICATE_REASON_LABELS[details.reason]}. Nothing has been saved yet.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <Button asChild type="button" variant="secondary">
          <Link href={`/jobs/${details.existing_job_id}`}>Open the job I have</Link>
        </Button>
        <Button type="button" variant="outline" onClick={onCreateAnyway}>
          Add it anyway
        </Button>
      </CardContent>
    </Card>
  );
}

function errorMessage(error: Error | null): string {
  if (!error) return "";
  if (error instanceof ApiError) {
    if (error.status === 422) return error.message;
    if (error.isUnauthenticated) return "Your session was not accepted. Sign out and back in.";
  }
  return "Could not save that job. Check your connection and try again.";
}
