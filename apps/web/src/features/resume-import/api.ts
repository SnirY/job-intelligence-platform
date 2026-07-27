"use client";

import {
  API_ROUTES,
  type ConfirmationResult,
  type ConfirmDecision,
  type ExtractionReview,
  type ImportAccepted,
  type ImportSummary,
  type ProcessingJob,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

export const importsQueryKey = ["resumes", "imports"] as const;

export function reviewQueryKey(documentId: string) {
  return ["resumes", "imports", documentId] as const;
}

/**
 * How often the review screen polls while work is in flight.
 *
 * `docs/10-api-contracts.md` sanctions 2–5 seconds until a terminal state.
 * Three keeps the progress readable without hammering the API.
 */
const POLL_INTERVAL_MS = 3000;

/** Whether a document is still being worked on. */
function isProcessing(review: ExtractionReview | undefined): boolean {
  if (!review) return false;
  const status = review.job?.status;
  return status === "PENDING" || status === "RUNNING";
}

export function useImports() {
  const api = useApi();

  return useQuery({
    queryKey: importsQueryKey,
    queryFn: () => api<ImportSummary[]>(API_ROUTES.resumeImports),
  });
}

/**
 * Upload a resume.
 *
 * No `Content-Type` header: the browser must set it itself so it can add the
 * multipart boundary. Setting it by hand produces a body the server cannot
 * parse, and the failure looks like a malformed request rather than a header
 * mistake.
 */
export function useUploadResume() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api<ImportAccepted>(API_ROUTES.resumeImport, { method: "POST", body });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: importsQueryKey }),
  });
}

/**
 * The review payload, polled while processing runs.
 *
 * Polling stops on its own once the job reaches a terminal state — a page left
 * open on a failed import should not keep asking forever.
 */
export function useExtractionReview(documentId: string | null) {
  const api = useApi();

  return useQuery({
    queryKey: reviewQueryKey(documentId ?? ""),
    enabled: documentId !== null,
    queryFn: () => api<ExtractionReview>(`${API_ROUTES.resumeImports}/${documentId}/extraction`),
    refetchInterval: (query) => (isProcessing(query.state.data) ? POLL_INTERVAL_MS : false),
  });
}

export function useConfirmExtraction(documentId: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (decisions: ConfirmDecision[]) =>
      api<ConfirmationResult>(`${API_ROUTES.resumeImports}/${documentId}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decisions }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: reviewQueryKey(documentId) });
      // The profile just changed, so every career list is stale.
      queryClient.invalidateQueries({ queryKey: ["career"] });
    },
  });
}

export function useRetryJob(documentId: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (jobId: string) =>
      api<ProcessingJob>(`${API_ROUTES.processingJobs}/${jobId}/retry`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: reviewQueryKey(documentId) });
      queryClient.invalidateQueries({ queryKey: importsQueryKey });
    },
  });
}
