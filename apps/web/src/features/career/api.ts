import {
  API_ROUTES,
  type CareerProfile,
  type CareerProfileUpdate,
  type TargetRole,
  type TargetRoleCreate,
  type TargetRoleUpdate,
} from "@jip/shared-types";

import type { ApiFetchOptions } from "@/lib/api";

export const careerProfileQueryKey = ["career", "profile"] as const;

type Api = <T>(path: string, options?: ApiFetchOptions) => Promise<T>;

export function fetchCareerProfile(api: Api): Promise<CareerProfile> {
  return api<CareerProfile>(API_ROUTES.careerProfile);
}

/**
 * Send only the fields the user actually changed.
 *
 * The endpoint is a PATCH, so an omitted key is left alone. Posting the whole
 * object back would overwrite a field edited elsewhere with a stale value read
 * when this form loaded.
 */
export function updateCareerProfile(api: Api, update: CareerProfileUpdate): Promise<CareerProfile> {
  return api<CareerProfile>(API_ROUTES.careerProfile, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

// --- target roles ------------------------------------------------------------

export const targetRolesQueryKey = ["career", "target-roles"] as const;

export function fetchTargetRoles(api: Api): Promise<TargetRole[]> {
  return api<TargetRole[]>(API_ROUTES.careerTargetRoles);
}

export function createTargetRole(api: Api, body: TargetRoleCreate): Promise<TargetRole> {
  return api<TargetRole>(API_ROUTES.careerTargetRoles, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateTargetRole(
  api: Api,
  id: string,
  body: TargetRoleUpdate,
): Promise<TargetRole> {
  return api<TargetRole>(`${API_ROUTES.careerTargetRoles}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Returns nothing: the endpoint answers 204 with no body. */
export function deleteTargetRole(api: Api, id: string): Promise<void> {
  return api<void>(`${API_ROUTES.careerTargetRoles}/${id}`, { method: "DELETE" });
}
