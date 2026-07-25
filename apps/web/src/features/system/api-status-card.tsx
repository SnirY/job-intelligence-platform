"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_BASE_URL } from "@/lib/api";
import { fetchHealth, healthQueryKey } from "@/features/system/api";

/**
 * Live view of the API connection.
 *
 * This is the Phase 0 proof that the browser can reach the backend. All three
 * states are rendered explicitly — a failure must be visible as a failure, not
 * as an empty card.
 */
export function ApiStatusCard() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: healthQueryKey,
    queryFn: fetchHealth,
  });

  return (
    <Card className="w-full max-w-xl">
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <CardTitle>API connection</CardTitle>
          {isPending ? (
            <Badge variant="secondary">Checking…</Badge>
          ) : error ? (
            <Badge variant="destructive">Unreachable</Badge>
          ) : (
            <Badge variant="success">Connected</Badge>
          )}
        </div>
        <CardDescription>{API_BASE_URL}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {isPending ? (
          <p className="text-sm text-muted-foreground">Contacting the API…</p>
        ) : error ? (
          <div className="space-y-1 text-sm">
            <p className="font-medium text-destructive">{error.message}</p>
            <p className="text-muted-foreground">
              Start the API with <code className="font-mono">uvicorn jip_api.main:app</code> or{" "}
              <code className="font-mono">docker compose up</code>.
            </p>
          </div>
        ) : (
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Service</dt>
            <dd className="font-mono">{data.service}</dd>
            <dt className="text-muted-foreground">Version</dt>
            <dd className="font-mono">{data.version}</dd>
            <dt className="text-muted-foreground">Environment</dt>
            <dd className="font-mono">{data.environment}</dd>
          </dl>
        )}

        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Checking…" : "Check again"}
        </Button>
      </CardContent>
    </Card>
  );
}
