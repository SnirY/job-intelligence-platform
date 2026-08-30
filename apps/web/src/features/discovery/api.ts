"use client";

import {
  API_ROUTES,
  type CollectionResponse,
  type DiscoveredPosting,
  type PromoteRequest,
  type PromotedPosting,
  type ScanQueued,
  type WatchedBoard,
  type WatchedBoardCreate,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetchPage } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useSessionToken } from "@/lib/use-api";

export const discoveryKey = ["discovery"] as const;
export const boardsKey = [...discoveryKey, "boards"] as const;
export const postingsKey = [...discoveryKey, "postings"] as const;

/**
 * How often the review list re-checks while a scan is running.
 *
 * A scan reads several third-party boards, so it takes longer than an import
 * and there is no status field to watch — the same problem the liveness check
 * has, solved the same way: the caller waiting on one says it is waiting.
 */
const POLL_INTERVAL_MS = 3000;

export function useWatchedBoards() {
  const api = useApi();

  return useQuery({
    queryKey: boardsKey,
    queryFn: () => api<WatchedBoard[]>(API_ROUTES.discoveryBoards),
  });
}

export function useProviders() {
  const api = useApi();

  return useQuery({
    queryKey: [...discoveryKey, "providers"],
    // The API is the authority on which providers exist, so the form offers
    // whatever it returns rather than a list the frontend keeps in step by hand.
    queryFn: () => api<string[]>(API_ROUTES.discoveryProviders),
    staleTime: 60 * 60 * 1000,
  });
}

export function useAddBoard() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: WatchedBoardCreate) =>
      api<WatchedBoard>(API_ROUTES.discoveryBoards, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: discoveryKey }),
  });
}

/** Pause, resume, or stop watching. */
export function useBoardAction(id: string, action: "pause" | "resume" | "remove") {
  const api = useApi();
  const queryClient = useQueryClient();

  // One return type across the three actions. Removal answers 204 and has
  // nothing to hand back, and a union of `void | WatchedBoard` would make every
  // caller narrow a value none of them reads.
  return useMutation<WatchedBoard | undefined>({
    mutationFn: async () => {
      if (action === "remove") {
        await api<void>(`${API_ROUTES.discoveryBoards}/${id}`, { method: "DELETE" });
        return undefined;
      }
      return api<WatchedBoard>(`${API_ROUTES.discoveryBoards}/${id}/${action}`, {
        method: "POST",
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: discoveryKey }),
  });
}

export function useScan() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api<ScanQueued>(API_ROUTES.discoveryScan, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: discoveryKey }),
  });
}

/**
 * Postings awaiting a decision.
 *
 * `poll` is passed by whatever is waiting on a scan, for the same reason
 * `useJob` takes one: the work finishes on the worker and announces nothing, so
 * the only signal is the list changing.
 */
export function usePendingPostings(options?: { poll?: boolean }) {
  const { getToken } = useSessionToken();

  return useQuery({
    queryKey: postingsKey,
    queryFn: () =>
      apiFetchPage<DiscoveredPosting>(API_ROUTES.discoveryPostings, {
        getToken: () => getToken(),
      }),
    placeholderData: (previous: CollectionResponse<DiscoveredPosting> | undefined) => previous,
    refetchInterval: options?.poll ? POLL_INTERVAL_MS : false,
  });
}

export function useDismissPosting() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      api<DiscoveredPosting>(`${API_ROUTES.discoveryPostings}/${id}/dismiss`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: discoveryKey }),
  });
}

/**
 * Turn a candidate into a job.
 *
 * The only call in the frontend that creates a job from a scan result, and it
 * happens because a person clicked. Nothing polls its way into the library.
 */
export function usePromotePosting() {
  const api = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, ...body }: PromoteRequest & { id: string }) =>
      api<PromotedPosting>(`${API_ROUTES.discoveryPostings}/${id}/promote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: discoveryKey });
      // The job library changed too, and the jobs list is very often the screen
      // the user came from.
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
