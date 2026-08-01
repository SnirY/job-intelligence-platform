"use client";

import { API_ROUTES, type Dashboard } from "@jip/shared-types";
import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

export const dashboardKey = ["dashboard"] as const;

/**
 * One request for the whole home screen.
 *
 * `docs/10-api-contracts.md` specifies a single aggregate endpoint, and the
 * reason shows up here: six queries would mean six loading states on the first
 * screen after signing in, and a page that cannot settle until the slowest of
 * them returns.
 *
 * No polling. Nothing on this screen changes without the user doing something
 * on another one, and coming back re-renders it.
 */
export function useDashboard() {
  const api = useApi();

  return useQuery({
    queryKey: dashboardKey,
    queryFn: () => api<Dashboard>(API_ROUTES.dashboard),
  });
}
