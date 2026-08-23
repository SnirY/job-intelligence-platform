"use client";

import { API_ROUTES, type FailedProcessingJob } from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/use-api";

/**
 * Background work that did not finish.
 *
 * Phase 11 carried retry flows as partial with one thing named: a dead-letter
 * path, and **any view across failures**. Retrying a job worked; finding one
 * did not. A failure was reachable only by its id, so the only person who ever
 * saw one was somebody already watching the screen it belonged to at the moment
 * it broke.
 *
 * On Settings rather than the dashboard deliberately. `/home` answers questions
 * about a job search — a stalled import is not one of them, and putting "3
 * imports failed" between "what to do next" and "your pipeline" would mix two
 * vocabularies on a screen whose whole value is that it does not.
 *
 * **Renders nothing when nothing has failed.** An empty panel headed "failures"
 * is a panel that trains you to ignore it, and this is the one place that must
 * still be read on the day it is not empty.
 */
export function FailedWork() {
  const failures = useFailedWork();
  const rows = failures.data ?? [];

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Work that did not finish</CardTitle>
        <CardDescription>
          Imports and analyses that stopped. Nothing you wrote was lost — this is only the
          background step.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.map((row) => (
          <FailureRow key={row.id} failure={row} />
        ))}
      </CardContent>
    </Card>
  );
}

function FailureRow({ failure }: { failure: FailedProcessingJob }) {
  const retry = useRetryFailure();

  return (
    <div className="grid gap-3 rounded-lg border p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-medium">{failure.entity_label ?? describeKind(failure.kind)}</p>
        <p className="text-sm text-muted-foreground">
          {failure.error_message ?? "It stopped without saying why."}
        </p>
        {/* The distinction the whole panel exists to draw. A row you can act on
          and a row that is over must not look the same. */}
        <p className="text-xs text-muted-foreground">
          {failure.can_be_retried
            ? `${describeKind(failure.kind)} · tried ${failure.attempts} of ${failure.max_attempts}`
            : `${describeKind(failure.kind)} · trying again will not help`}
        </p>
      </div>

      {failure.can_be_retried && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={retry.isPending}
          onClick={() => retry.mutate(failure.id)}
        >
          <RotateCw aria-hidden className="size-3.5" />
          Try again
        </Button>
      )}
    </div>
  );
}

/** What the work was, in the user's terms rather than the queue's. */
function describeKind(kind: string): string {
  if (kind === "RESUME_IMPORT") return "Reading a resume";
  if (kind === "JOB_ANALYSIS") return "Reading a posting";
  return "Background work";
}

const failuresKey = ["processing-failures"] as const;

function useFailedWork() {
  const api = useApi();

  return useQuery({
    queryKey: failuresKey,
    queryFn: () => api<FailedProcessingJob[]>(API_ROUTES.processingFailures),
  });
}

function useRetryFailure() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api<unknown>(`${API_ROUTES.processingJobs}/${id}/retry`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: failuresKey });
      // The thing that failed lives somewhere else too — a job, a resume — and
      // a retry changes its state.
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
    },
  });
}
