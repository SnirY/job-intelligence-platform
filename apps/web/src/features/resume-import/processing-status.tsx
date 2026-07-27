"use client";

import type { ProcessingJob, ProcessingStep, SourceDocument } from "@jip/shared-types";
import { AlertTriangle, CheckCircle2, Loader2, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** What each step means in the user's terms, not the pipeline's. */
const STEP_LABELS: Record<ProcessingStep, string> = {
  QUEUED: "Waiting to start",
  EXTRACTING: "Reading your document",
  PARSING: "Finding your experience, skills, and education",
  COMPLETED: "Done",
};

const STEP_ORDER: readonly ProcessingStep[] = ["QUEUED", "EXTRACTING", "PARSING", "COMPLETED"];

interface ProcessingStatusProps {
  document: SourceDocument;
  job: ProcessingJob | null;
  onRetry: () => void;
  isRetrying: boolean;
  retryFailed: boolean;
}

export function ProcessingStatus({
  document,
  job,
  onRetry,
  isRetrying,
  retryFailed,
}: ProcessingStatusProps) {
  if (job?.status === "FAILED") {
    return (
      <FailureCard
        document={document}
        job={job}
        onRetry={onRetry}
        isRetrying={isRetrying}
        retryFailed={retryFailed}
      />
    );
  }

  const current = job?.step ?? "QUEUED";
  const currentIndex = STEP_ORDER.indexOf(current);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Reading {document.original_filename}
        </CardTitle>
        <CardDescription>
          This usually takes under a minute. You can leave this page — the import keeps running.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <ol className="space-y-2" aria-live="polite">
          {STEP_ORDER.filter((step) => step !== "COMPLETED").map((step, index) => {
            const done = index < currentIndex;
            const active = index === currentIndex;
            return (
              <li key={step} className="flex items-center gap-2 text-sm">
                {done ? (
                  <CheckCircle2 aria-hidden className="size-4 text-success" />
                ) : active ? (
                  <Loader2 aria-hidden className="size-4 animate-spin text-primary" />
                ) : (
                  <span
                    aria-hidden
                    className="size-4 rounded-full border border-muted-foreground/40"
                  />
                )}
                <span className={done || active ? "" : "text-muted-foreground"}>
                  {STEP_LABELS[step]}
                </span>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

function FailureCard({
  document,
  job,
  onRetry,
  isRetrying,
  retryFailed,
}: {
  document: SourceDocument;
  job: ProcessingJob;
  onRetry: () => void;
  isRetrying: boolean;
  retryFailed: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle aria-hidden className="size-4 text-destructive" />
          Could not read {document.original_filename}
        </CardTitle>
        <CardDescription>
          {/* GOAL.md: a failure must not destroy user work. Saying so plainly is
              what stops the user re-uploading a file that is already stored. */}
          Your file is safe — nothing was lost.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <p className="text-sm">
          {job.error_message ?? "Something went wrong while processing it."}
        </p>

        {job.is_retriable ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" disabled={isRetrying} onClick={onRetry}>
              <RotateCw aria-hidden className="size-4" />
              {isRetrying ? "Starting again…" : "Try again"}
            </Button>
            <span className="text-xs text-muted-foreground">
              Attempt {job.attempts} of {job.max_attempts}
            </span>
          </div>
        ) : (
          // No retry button when a retry cannot help. Offering one for a
          // scanned PDF would just fail again and look broken.
          <p className="text-sm text-muted-foreground">
            Trying again will not help with this one. Upload a different file instead.
          </p>
        )}

        <p aria-live="polite" className="text-sm text-destructive">
          {retryFailed && "Could not start it again. Try once more in a moment."}
        </p>
      </CardContent>
    </Card>
  );
}
