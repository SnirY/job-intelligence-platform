"use client";

import { API_ROUTES, type SkillDemandReport, type SkillGapReport } from "@jip/shared-types";
import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

export const insightsKey = ["insights"] as const;

/**
 * Demand and gaps in two requests rather than one.
 *
 * Unlike the dashboard, these are two views of the same underlying count and
 * the screen shows them side by side — but they are separate routes in
 * `docs/10`, and collapsing them here would mean the API served a shape no
 * endpoint describes.
 */
export function useSkillDemand() {
  const api = useApi();

  return useQuery({
    queryKey: [...insightsKey, "demand"],
    queryFn: () => api<SkillDemandReport>(API_ROUTES.insightsSkillDemand),
  });
}

export function useSkillGaps() {
  const api = useApi();

  return useQuery({
    queryKey: [...insightsKey, "gaps"],
    queryFn: () => api<SkillGapReport>(API_ROUTES.insightsSkillGaps),
  });
}
