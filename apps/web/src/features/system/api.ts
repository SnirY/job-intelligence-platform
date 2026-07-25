import { API_ROUTES, type CurrentUser, type HealthPayload } from "@jip/shared-types";

import { apiFetch } from "@/lib/api";

/** Fetch the API liveness payload. Requires no authentication. */
export function fetchHealth(): Promise<HealthPayload> {
  return apiFetch<HealthPayload>(API_ROUTES.health);
}

export const healthQueryKey = ["system", "health"] as const;

/** Query key for the authenticated user. */
export const currentUserQueryKey = ["system", "current-user"] as const;

export { API_ROUTES };
export type { CurrentUser };
