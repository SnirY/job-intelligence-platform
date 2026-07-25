"use client";

import { useQuery } from "@tanstack/react-query";
import { API_ROUTES, type CurrentUser } from "@jip/shared-types";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { currentUserQueryKey } from "@/features/system/api";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/**
 * Live view of the authenticated API connection.
 *
 * This is the Phase 1 proof that the whole chain works: Clerk session, bearer
 * token, JWKS verification, internal user record. All three states render
 * explicitly, so a failure is visible as a failure rather than an empty card.
 */
export function AccountStatusCard() {
  const api = useApi();

  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: currentUserQueryKey,
    queryFn: () => api<CurrentUser>(API_ROUTES.currentUser),
  });

  const unauthenticated = error instanceof ApiError && error.isUnauthenticated;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <CardTitle className="text-base">Account</CardTitle>
          {isPending ? (
            <Badge variant="secondary">Checking…</Badge>
          ) : unauthenticated ? (
            <Badge variant="destructive">Not authenticated</Badge>
          ) : error ? (
            <Badge variant="destructive">Unreachable</Badge>
          ) : (
            <Badge variant="success">Verified</Badge>
          )}
        </div>
        <CardDescription>
          Your session, verified by the API against the authentication provider.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {isPending ? (
          <p className="text-sm text-muted-foreground">Verifying your session…</p>
        ) : error ? (
          <div className="space-y-1 text-sm">
            <p className="font-medium text-destructive">
              {unauthenticated
                ? "The API did not accept this session."
                : "Could not reach the API."}
            </p>
            <p className="text-muted-foreground">
              {unauthenticated
                ? "Try signing out and back in. If it persists, the API's authentication settings may not match this application."
                : error.message}
            </p>
          </div>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Account ID</dt>
            <dd className="font-mono text-xs break-all">{data.id}</dd>
            <dt className="text-muted-foreground">Email</dt>
            <dd>{data.email ?? <span className="text-muted-foreground">Not provided</span>}</dd>
            <dt className="text-muted-foreground">Member since</dt>
            <dd>{new Date(data.created_at).toLocaleDateString()}</dd>
          </dl>
        )}

        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Checking…" : "Check again"}
        </Button>
      </CardContent>
    </Card>
  );
}
