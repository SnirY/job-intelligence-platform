"use client";

import {
  API_ROUTES,
  type FinalizeResult,
  type Resume,
  type ResumeFamily,
  type ResumeStrategyView,
  type ResumeSuggestion,
  type ResumeVersion,
  type ResumeVersionDetail,
  type ResumeVersionStatus,
} from "@jip/shared-types";
import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE_URL } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export const resumesKey = ["resumes"] as const;

export function resumeKey(id: string) {
  return ["resumes", id] as const;
}

export function versionKey(id: string) {
  return ["resume-versions", id] as const;
}

export function strategyKey(jobId: string) {
  return ["jobs", jobId, "resume-strategy"] as const;
}

export function useResumes(includeArchived = false) {
  const api = useApi();
  return useQuery({
    queryKey: [...resumesKey, { includeArchived }],
    queryFn: () => api<Resume[]>(`${API_ROUTES.resumes}?include_archived=${includeArchived}`),
  });
}

export function useResume(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: resumeKey(id),
    queryFn: () => api<Resume>(`${API_ROUTES.resumes}/${id}`),
  });
}

export function useVersions(resumeId: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...resumeKey(resumeId), "versions"],
    queryFn: () => api<ResumeVersion[]>(`${API_ROUTES.resumes}/${resumeId}/versions`),
  });
}

export function useVersion(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: versionKey(id ?? "none"),
    // Only once a version is chosen: the editor mounts before one is.
    enabled: Boolean(id),
    queryFn: () => api<ResumeVersionDetail>(`${API_ROUTES.resumeVersions}/${id}`),
  });
}

export function useCreateResume() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; family: ResumeFamily; description?: string | null }) =>
      api<Resume>(API_ROUTES.resumes, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: resumesKey }),
  });
}

export function useCreateVersion(resumeId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { label?: string | null; copy_from?: string | null }) =>
      api<ResumeVersionDetail>(`${API_ROUTES.resumes}/${resumeId}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: resumeKey(resumeId) }),
  });
}

/** Replace a version's whole content. Refused for a used or archived version. */
export function useSaveContent(versionId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) =>
      api<ResumeVersionDetail>(`${API_ROUTES.resumeVersions}/${versionId}/content`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: versionKey(versionId) }),
  });
}

export function useSetVersionStatus(versionId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (status: ResumeVersionStatus) =>
      api<ResumeVersion>(`${API_ROUTES.resumeVersions}/${versionId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: versionKey(versionId) });
      void queryClient.invalidateQueries({ queryKey: resumesKey });
    },
  });
}

/**
 * Fetch a version's printable HTML.
 *
 * Not a plain link. The render endpoint is on the API origin and is
 * authenticated, so an `<a href>` would arrive without the bearer token and get
 * a 401 — the same check that stops one user downloading another's resume.
 *
 * Returns the HTML rather than opening a window, so the caller can open the
 * window on the click itself and avoid the popup blocker.
 */
export function useRenderVersion() {
  const { getToken } = useAuth();
  return useMutation({
    mutationFn: async (versionId: string) => {
      const token = await getToken();
      const response = await fetch(
        `${API_BASE_URL}${API_ROUTES.resumeVersions}/${versionId}/render`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!response.ok) {
        throw new Error(`The resume could not be rendered (HTTP ${response.status}).`);
      }
      return response.text();
    },
  });
}

// --- tailoring ----------------------------------------------------------------

export function useStrategy(jobId: string) {
  const api = useApi();
  return useQuery({
    queryKey: strategyKey(jobId),
    queryFn: () => api<ResumeStrategyView>(`${API_ROUTES.jobs}/${jobId}/resume-strategies`),
  });
}

export function useCreateStrategy(jobId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<ResumeStrategyView>(`${API_ROUTES.jobs}/${jobId}/resume-strategies`, {
        method: "POST",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKey(jobId) }),
  });
}

export function useCreateSuggestions(jobId: string, strategyId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) =>
      api<ResumeStrategyView>(
        `${API_ROUTES.resumeStrategies}/${strategyId}/suggestions?version_id=${versionId}`,
        { method: "POST" },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKey(jobId) }),
  });
}

/** Accept, reject, or edit one suggestion. */
export function useDecideSuggestion(jobId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
      text,
    }: {
      id: string;
      decision: "accept" | "reject" | "edit";
      text?: string;
    }) =>
      api<ResumeSuggestion>(`${API_ROUTES.resumeSuggestions}/${id}/${decision}`, {
        method: "POST",
        ...(decision === "edit"
          ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) }
          : {}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKey(jobId) }),
  });
}

export function useFinalize(jobId: string, strategyId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { resume_id: string; label?: string | null }) =>
      api<FinalizeResult>(`${API_ROUTES.resumeStrategies}/${strategyId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: strategyKey(jobId) });
      void queryClient.invalidateQueries({ queryKey: resumesKey });
    },
  });
}
