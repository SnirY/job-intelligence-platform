"use client";

import {
  API_ROUTES,
  type CoverLetter,
  type CoverLetterDraftRequest,
  type CoverLetterEditRequest,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

export function coverLetterKey(jobId: string) {
  return ["jobs", jobId, "cover-letter"] as const;
}

/**
 * How often to re-check while a draft is being written.
 *
 * `docs/10-api-contracts.md` sanctions 2–5 seconds until a terminal state.
 * Unlike a liveness check, a cover letter *has* a status to watch, so polling
 * stops on its own rather than needing a caller to say it is waiting.
 */
const POLL_INTERVAL_MS = 3000;

export function useCoverLetter(jobId: string) {
  const api = useApi();

  return useQuery({
    queryKey: coverLetterKey(jobId),
    queryFn: () => api<CoverLetter | null>(`${API_ROUTES.jobs}/${jobId}/cover-letter`),
    refetchInterval: (result) =>
      result.state.data?.status === "DRAFTING" ? POLL_INTERVAL_MS : false,
  });
}

export function useDraftCoverLetter(jobId: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CoverLetterDraftRequest) =>
      api<CoverLetter>(`${API_ROUTES.jobs}/${jobId}/cover-letter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: coverLetterKey(jobId) }),
  });
}

export function useEditCoverLetter(letterId: string, jobId: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CoverLetterEditRequest) =>
      api<CoverLetter>(`${API_ROUTES.coverLetters}/${letterId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: coverLetterKey(jobId) }),
  });
}

export function useApproveCoverLetter(letterId: string, jobId: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      api<CoverLetter>(`${API_ROUTES.coverLetters}/${letterId}/approve`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: coverLetterKey(jobId) }),
  });
}
