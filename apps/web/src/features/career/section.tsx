"use client";

import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";

interface CollectionSectionProps<TItem> {
  title: string;
  description: string;
  items: TItem[] | undefined;
  isPending: boolean;
  error: Error | null;
  /** Shown when the collection loads successfully and is empty. */
  emptyMessage: string;
  renderItem: (item: TItem) => ReactNode;
  /** The add form, always available regardless of list state. */
  form: ReactNode;
}

/**
 * Shared frame for a career collection.
 *
 * Centralising the four states means none of the sections can quietly forget
 * one — an unhandled error state renders as an empty list, which reads as
 * "you have nothing" rather than "we could not load this".
 */
export function CollectionSection<TItem extends { id: string }>({
  title,
  description,
  items,
  isPending,
  error,
  emptyMessage,
  renderItem,
  form,
}: CollectionSectionProps<TItem>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {error ? (
          <p className="text-sm text-destructive">
            {error instanceof ApiError && error.isUnauthenticated
              ? "Your session was not accepted. Try signing out and back in."
              : `Could not load ${title.toLowerCase()}.`}
          </p>
        ) : isPending || !items ? (
          <p className="text-sm text-muted-foreground">Loading {title.toLowerCase()}…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-start gap-3 p-3">
                {renderItem(item)}
              </li>
            ))}
          </ul>
        )}

        <div className="border-t pt-4">{form}</div>
      </CardContent>
    </Card>
  );
}

/** Formats a start/end pair, or "Present" for a current entry. */
export function formatDateRange(
  start: string | null,
  end: string | null,
  isCurrent = false,
): string | null {
  const year = (value: string | null) => (value ? value.slice(0, 7) : null);
  const from = year(start);
  const to = isCurrent ? "Present" : year(end);

  if (!from && !to) return null;
  if (from && to) return `${from} – ${to}`;
  return from ?? to;
}
