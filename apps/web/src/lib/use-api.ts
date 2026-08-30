"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useMemo } from "react";

import { apiFetch, type ApiFetchOptions, type TokenProvider } from "@/lib/api";
import { isLocalAuth, LOCAL_SESSION_COOKIE } from "@/lib/auth-mode";

/** Calls the API with the session's bearer token attached. */
type BoundApiFetch = <T>(path: string, options?: ApiFetchOptions) => Promise<T>;

/** The local session token from its cookie, or `null`. */
function localToken(): string | null {
  if (typeof document === "undefined") return null;

  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${LOCAL_SESSION_COOKIE}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

function useClerkToken(): { getToken: TokenProvider } {
  const { getToken } = useAuth();

  return useMemo(() => ({ getToken: () => getToken() }), [getToken]);
}

function useLocalTokenProvider(): { getToken: TokenProvider } {
  return useMemo(() => ({ getToken: () => Promise.resolve(localToken()) }), []);
}

/**
 * The current session's bearer token, whichever mode the build runs.
 *
 * Shaped like Clerk's `useAuth()` so a caller reads the same either way. Every
 * query that talks to the API goes through this rather than reaching for
 * `useAuth` directly — a module that imports the Clerk hook straight is one
 * that crashes the moment local mode removes the provider above it, and it
 * crashes on whichever screen happens to mount it rather than at the boundary.
 */
export const useSessionToken: () => { getToken: TokenProvider } = isLocalAuth
  ? useLocalTokenProvider
  : useClerkToken;

function useClerkApi(): BoundApiFetch {
  const { getToken } = useClerkToken();

  return useCallback((path, options = {}) => apiFetch(path, { ...options, getToken }), [getToken]);
}

function useLocalApi(): BoundApiFetch {
  const { getToken } = useLocalTokenProvider();

  return useCallback((path, options = {}) => apiFetch(path, { ...options, getToken }), [getToken]);
}

/**
 * Returns an `apiFetch` bound to the current session.
 *
 * The token is fetched inside the returned function, not captured when the hook
 * runs. Clerk session tokens are short-lived and refreshed by the SDK, so a
 * token read once at mount would start failing while the page is still open.
 * The local cookie is read per request for the same reason: it expires too, and
 * signing out clears it under a page that is still mounted.
 *
 * Which implementation is used is decided once, here, rather than branched
 * inside the hook. `useAuth` needs a `ClerkProvider` above it and that provider
 * is not mounted in local mode, so calling it there would throw — and a branch
 * inside a hook would be one anyway. `isLocalAuth` is fixed for the lifetime of
 * the bundle, so the hook a component calls never changes between renders.
 */
export const useApi: () => BoundApiFetch = isLocalAuth ? useLocalApi : useClerkApi;
