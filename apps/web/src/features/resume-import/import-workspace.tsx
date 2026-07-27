"use client";

import { useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { useExtractionReview, useImports, useRetryJob } from "@/features/resume-import/api";
import { ProcessingStatus } from "@/features/resume-import/processing-status";
import { ReviewPanel } from "@/features/resume-import/review-panel";
import { UploadCard } from "@/features/resume-import/upload-card";
import { ApiError } from "@/lib/api";

/**
 * The whole import flow on one screen.
 *
 * Upload -> progress -> review -> confirm, with failure and retry handled at
 * the point they occur. One page rather than a wizard because the user is
 * doing one thing, and losing their place between steps would mean losing the
 * decisions they had already made.
 */
export function ImportWorkspace() {
  const imports = useImports();
  const [selected, setSelected] = useState<string | null>(null);

  // Falls back to the most recent upload so a reload lands back where the user
  // was, rather than on an empty screen with an import running invisibly.
  const documentId = selected ?? imports.data?.[0]?.document.id ?? null;

  return (
    <div className="space-y-6">
      <UploadCard onUploaded={setSelected} />

      {imports.isError && (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">
              {imports.error instanceof ApiError && imports.error.isUnauthenticated
                ? "Your session was not accepted. Try signing out and back in."
                : "Could not load your imports."}
            </p>
          </CardContent>
        </Card>
      )}

      {documentId && <ImportDetail documentId={documentId} />}
    </div>
  );
}

function ImportDetail({ documentId }: { documentId: string }) {
  const review = useExtractionReview(documentId);
  const retry = useRetryJob(documentId);

  if (review.isPending) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Loading your import…</p>
        </CardContent>
      </Card>
    );
  }

  if (review.isError || !review.data) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-destructive">Could not load this import.</p>
        </CardContent>
      </Card>
    );
  }

  const { document, job, extraction } = review.data;

  // Progress and failure share a component: a failed job is a terminal state of
  // the same process, and the retry button belongs beside the step that failed.
  if (!extraction || job?.status === "FAILED") {
    return (
      <ProcessingStatus
        document={document}
        job={job}
        isRetrying={retry.isPending}
        retryFailed={retry.isError}
        onRetry={() => {
          if (job) retry.mutate(job.id);
        }}
      />
    );
  }

  return <ReviewPanel documentId={documentId} extraction={extraction} />;
}
