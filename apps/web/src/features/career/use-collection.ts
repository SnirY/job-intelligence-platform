"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/lib/use-api";

/**
 * List/create/delete for one career collection.
 *
 * The four sections differ in their fields, not in how they talk to the API.
 * Writing the query keys, invalidation, and error plumbing four times would
 * mean four chances to forget an invalidation and leave the screen showing
 * something the server no longer holds.
 */
export function useCollection<TItem extends { id: string }, TCreate>(
  key: readonly string[],
  path: string,
) {
  const api = useApi();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: key,
    queryFn: () => api<TItem[]>(path),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: (body: TCreate) =>
      api<TItem>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    // The endpoint answers 204 with no body, which apiFetch returns as
    // undefined rather than treating as a parse failure.
    mutationFn: (id: string) => api<void>(`${path}/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<TCreate> }) =>
      api<TItem>(`${path}/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });

  return { query, create, remove, update };
}
