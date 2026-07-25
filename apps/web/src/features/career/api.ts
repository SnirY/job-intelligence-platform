import { API_ROUTES, type CareerProfile, type CareerProfileUpdate } from "@jip/shared-types";

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
