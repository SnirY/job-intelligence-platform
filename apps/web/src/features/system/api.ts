import { API_ROUTES, type HealthPayload } from "@jip/shared-types";

import { apiFetch } from "@/lib/api";

/** Fetch the API liveness payload. */
export function fetchHealth(): Promise<HealthPayload> {
  return apiFetch<HealthPayload>(API_ROUTES.health);
}

export const healthQueryKey = ["system", "health"] as const;
