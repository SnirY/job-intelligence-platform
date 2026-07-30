"use client";

import {
  API_ROUTES,
  type Application,
  type ApplicationEvent,
  type ApplicationSource,
  type ApplicationStatus,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

export const applicationsKey = ["applications"] as const;

export function applicationKey(id: string) {
  return ["applications", id] as const;
}

export function useApplications(includeArchived = false) {
  const api = useApi();
  return useQuery({
    queryKey: [...applicationsKey, { includeArchived }],
    queryFn: () =>
      api<Application[]>(`${API_ROUTES.applications}?include_archived=${includeArchived}`),
  });
}

export function useApplication(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: applicationKey(id),
    queryFn: () => api<Application>(`${API_ROUTES.applications}/${id}`),
  });
}

export function useEvents(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...applicationKey(id), "events"],
    queryFn: () => api<ApplicationEvent[]>(`${API_ROUTES.applications}/${id}/events`),
  });
}

export function useCreateApplication() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { job_id: string; status?: ApplicationStatus; notes?: string }) =>
      api<Application>(API_ROUTES.applications, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: applicationsKey }),
  });
}

/**
 * Move an application to another status.
 *
 * No optimistic update. A move the lifecycle forbids comes back 409 with a
 * written reason, and a card that slid into a column before the server agreed
 * would have to slide back — which reads as a glitch rather than a refusal.
 */
export function useChangeStatus() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: ApplicationStatus }) =>
      api<Application>(`${API_ROUTES.applications}/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: applicationsKey });
      void queryClient.invalidateQueries({ queryKey: applicationKey(variables.id) });
    },
  });
}

export function useMarkApplied(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      resume_version_id?: string | null;
      source?: ApplicationSource | null;
      applied_at?: string | null;
    }) =>
      api<Application>(`${API_ROUTES.applications}/${id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: applicationsKey });
      void queryClient.invalidateQueries({ queryKey: applicationKey(id) });
      // The attached version is frozen as USED, so the resume screens are stale.
      void queryClient.invalidateQueries({ queryKey: ["resumes"] });
    },
  });
}

export function useAddNote(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<ApplicationEvent>(`${API_ROUTES.applications}/${id}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: applicationKey(id) }),
  });
}

export function useRecordFeedback(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string) =>
      api<Application>(`${API_ROUTES.applications}/${id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: applicationKey(id) }),
  });
}
