"use client";

import {
  API_ROUTES,
  isAnalysisRunning,
  type CollectionResponse,
  type Job,
  type JobAnalysisView,
  type JobCreate,
  type JobListQuery,
  type JobMatchView,
  type JobSource,
  type JobSummary,
  type JobUpdate,
  type StartedAnalysis,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetchPage } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useAuth } from "@clerk/nextjs";

export const jobsKey = ["jobs"] as const;

export function jobKey(id: string) {
  return ["jobs", id] as const;
}

/**
 * How often the list re-checks while an import is in flight.
 *
 * `docs/10-api-contracts.md` sanctions 2–5 seconds until a terminal state.
 * Polling stops on its own once nothing is fetching, so a list left open on a
 * finished workspace is quiet.
 */
const POLL_INTERVAL_MS = 3000;

function toSearchParams(query: JobListQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // Empty strings are how the filter selects express "no filter"; sending
    // them would be asking the API for jobs whose work mode is "".
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function useJobs(query: JobListQuery) {
  const { getToken } = useAuth();

  return useQuery({
    // The query is part of the key, so changing a filter fetches rather than
    // showing the previous filter's results.
    queryKey: [...jobsKey, query],
    queryFn: () =>
      apiFetchPage<JobSummary>(`${API_ROUTES.jobs}${toSearchParams(query)}`, {
        getToken: () => getToken(),
      }),
    // Keeps the previous page on screen while the next one loads, so paging
    // does not flash an empty list.
    placeholderData: (previous: CollectionResponse<JobSummary> | undefined) => previous,
    refetchInterval: (result) =>
      result.state.data?.data.some((job) => job.status === "FETCHING") ? POLL_INTERVAL_MS : false,
  });
}

export function useJob(id: string) {
  const api = useApi();

  return useQuery({
    queryKey: jobKey(id),
    queryFn: () => api<Job>(`${API_ROUTES.jobs}/${id}`),
    refetchInterval: (result) =>
      result.state.data?.status === "FETCHING" ? POLL_INTERVAL_MS : false,
  });
}

export function useJobSource(id: string, enabled: boolean) {
  const api = useApi();

  return useQuery({
    queryKey: [...jobKey(id), "source"],
    // Fetched only when the user opens the source panel: the raw HTML of a job
    // page is large and almost never looked at.
    enabled,
    queryFn: () => api<JobSource>(`${API_ROUTES.jobs}/${id}/source`),
  });
}

export function useCompanies() {
  const api = useApi();

  return useQuery({
    queryKey: [...jobsKey, "companies"],
    queryFn: () => api<string[]>(API_ROUTES.jobCompanies),
  });
}

export function useCreateJob() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: JobCreate) =>
      api<Job>(API_ROUTES.jobs, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsKey }),
  });
}

export function useUpdateJob(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: JobUpdate) =>
      api<Job>(`${API_ROUTES.jobs}/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsKey }),
  });
}

/** Fill in a description by hand after a URL import failed. */
export function useSupplyDescription(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (description: string) =>
      api<Job>(`${API_ROUTES.jobs}/${id}/description`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsKey }),
  });
}

/** Archive, unarchive, or retry — the one-shot actions on a job. */
export function useJobAction(id: string, action: "archive" | "unarchive" | "retry-import") {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api<Job>(`${API_ROUTES.jobs}/${id}/${action}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsKey }),
  });
}

export function useDeleteJob() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api<void>(`${API_ROUTES.jobs}/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobsKey }),
  });
}

// --- analysis -----------------------------------------------------------------

export function analysisKey(id: string, version?: number) {
  return version
    ? (["jobs", id, "analysis", version] as const)
    : (["jobs", id, "analysis"] as const);
}

/**
 * A job's analysis, its requirements, and its responsibilities.
 *
 * One query rather than three: they are always rendered together, and
 * splitting them would make a job with no analysis yet cost three round trips
 * to discover that.
 */
export function useJobAnalysis(id: string, version?: number) {
  const api = useApi();
  const suffix = version ? `?version=${version}` : "";

  return useQuery({
    queryKey: analysisKey(id, version),
    queryFn: () => api<JobAnalysisView>(`${API_ROUTES.jobs}/${id}/analysis${suffix}`),
    // Polls only while an analysis is actually running, so a job left open on
    // a finished screen is quiet. Terminal states stop it on their own.
    refetchInterval: (result) =>
      result.state.data && isAnalysisRunning(result.state.data.job_status)
        ? POLL_INTERVAL_MS
        : false,
  });
}

/** Start an analysis, or a reanalysis. The same operation either way. */
export function useAnalyzeJob(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api<StartedAnalysis>(`${API_ROUTES.jobs}/${id}/analysis`, { method: "POST" }),
    onSuccess: () => {
      // Both: the analysis view carries the status the poll watches, and the
      // job itself carries the status the list badge reads.
      void queryClient.invalidateQueries({ queryKey: analysisKey(id) });
      void queryClient.invalidateQueries({ queryKey: jobsKey });
    },
  });
}

// --- matching -----------------------------------------------------------------

export function matchKey(id: string, version?: number) {
  return version ? (["jobs", id, "match", version] as const) : (["jobs", id, "match"] as const);
}

/**
 * A job's match, its items, and their evidence.
 *
 * No polling: matching is arithmetic over data already in the database, so the
 * POST returns the finished result rather than a job to watch.
 */
export function useJobMatch(id: string, version?: number) {
  const api = useApi();
  const suffix = version ? `?version=${version}` : "";

  return useQuery({
    queryKey: matchKey(id, version),
    queryFn: () => api<JobMatchView>(`${API_ROUTES.jobs}/${id}/match${suffix}`),
  });
}

/** Compute a match, or recompute one. The same operation either way. */
export function useMatchJob(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api<JobMatchView>(`${API_ROUTES.jobs}/${id}/match`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: matchKey(id) });
      void queryClient.invalidateQueries({ queryKey: jobsKey });
    },
  });
}
