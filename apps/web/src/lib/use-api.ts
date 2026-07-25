"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";

import { apiFetch, type ApiFetchOptions } from "@/lib/api";

/**
 * Returns an `apiFetch` bound to the current Clerk session.
 *
 * The token is fetched inside the returned function, not captured when the hook
 * runs. Clerk session tokens are short-lived and refreshed by the SDK, so a
 * token read once at mount would start failing while the page is still open.
 */
export function useApi() {
  const { getToken } = useAuth();

  return useCallback(
    <T>(path: string, options: ApiFetchOptions = {}) =>
      apiFetch<T>(path, { ...options, getToken: () => getToken() }),
    [getToken],
  );
}
