"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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

/**
 * The add form, reused for editing.
 *
 * `docs/03-domain-model.md` treats the career profile as the source of truth,
 * which only holds if it can be corrected. Until this existed, fixing a typo
 * meant deleting the row and retyping it — and on an experience that also
 * destroyed its achievements, because they are children of the row being
 * deleted (DEV-014).
 *
 * One form rather than two: an edit form is the add form with values in it, and
 * a second copy of six fields is a second place to forget a validation rule.
 */
export function useDraft<TDraft>(empty: TDraft) {
  const [draft, setDraft] = useState<TDraft>(empty);
  const [editingId, setEditingId] = useState<string | null>(null);

  return {
    draft,
    setDraft,
    editingId,
    isEditing: editingId !== null,

    /** Load an existing record into the form. */
    edit: (id: string, values: TDraft) => {
      setDraft(values);
      setEditingId(id);
    },

    /** Back to an empty add form. Used after a save and by Cancel. */
    reset: () => {
      setDraft(empty);
      setEditingId(null);
    },
  };
}
