"use client";

import type { JobListQuery, SavedJobView, SavedViewFilters } from "@jip/shared-types";
import { AlertTriangle, Bookmark, Check, Plus, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Input } from "@/components/ui/input";
import { useDeleteJobView, useJobViews, useSaveJobView } from "@/features/jobs/api";

/**
 * Places in the list, kept by name.
 *
 * Reaching a subset is already cheap — there are nine filters and a band
 * histogram that is itself a control. Coming *back* to one is not: the
 * combinations worth returning to are the ones somebody invented, and
 * "remote, nothing blocking, seventy up" has to be rebuilt from memory every
 * time. A saved view is that combination with a name on it.
 *
 * The row states which view is showing, and stops claiming it the moment a
 * filter moves. A chip that stays lit while the query underneath it has
 * changed is telling the reader they are somewhere they are not — and unlike
 * most wrong labels this one is invisible, because the list still looks
 * plausible.
 */
export function SavedViews({
  query,
  onApply,
}: {
  query: JobListQuery;
  onApply: (filters: SavedViewFilters) => void;
}) {
  const views = useJobViews();
  const save = useSaveJobView();
  const remove = useDeleteJobView();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const saved = views.data ?? [];
  const current = comparable(query);
  const showing = saved.find((view) => sameQuestion(view.filters, current));

  if (views.isPending || (saved.length === 0 && !naming && isEverything(current))) {
    // Nothing saved and nothing worth saving. The control appears when there
    // is a question on screen to name, rather than sitting empty on first
    // visit asking to be understood.
    return null;
  }

  return (
    <section aria-labelledby="saved-views-heading" className="space-y-2">
      <h2 id="saved-views-heading" className="sr-only">
        Saved views
      </h2>

      <div className="flex flex-wrap items-center gap-2">
        {saved.map((view) => (
          <ViewChip
            key={view.id}
            view={view}
            showing={view.id === showing?.id}
            onApply={() => onApply(view.filters)}
            onDelete={() => remove.mutate(view.id)}
            deleting={remove.isPending}
          />
        ))}

        {naming ? (
          <form
            className="flex items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) return;
              save.mutate(
                { name: name.trim(), filters: current },
                {
                  onSuccess: () => {
                    setNaming(false);
                    setName("");
                  },
                },
              );
            }}
          >
            <Input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Name this view"
              aria-label="Name this view"
              maxLength={80}
              className="h-8 w-48"
            />
            <Button type="submit" size="sm" disabled={!name.trim() || save.isPending}>
              <Check aria-hidden className="size-3.5" />
              Save
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setNaming(false);
                setName("");
                save.reset();
              }}
            >
              Cancel
            </Button>
          </form>
        ) : (
          !showing && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setNaming(true)}
              className="h-8"
            >
              <Plus aria-hidden className="size-3.5" />
              Save this view
            </Button>
          )
        )}
      </div>

      {save.isError && (
        <Callout tone="caution">
          {/* The API refuses a repeated name rather than overwriting, because
              "update this" and "I forgot I had one" are two different things
              and the destructive reading is not one to guess. */}
          That view could not be saved. You may already have one with that name.
        </Callout>
      )}
    </section>
  );
}

function ViewChip({
  view,
  showing,
  onApply,
  onDelete,
  deleting,
}: {
  view: SavedJobView;
  showing: boolean;
  onApply: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  if (!view.is_readable) {
    /* Refused rather than run. The stored filter is still there and still
       means something; this version of the app just cannot honour it, and
       running the view without it would show a wider list than the name
       promises with nothing saying so. */
    return (
      <span
        className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed px-3 text-sm text-muted-foreground"
        title={`Saved with ${view.unreadable.join(", ")}`}
      >
        <AlertTriangle aria-hidden className="size-3.5" />
        {view.name}
        <span className="sr-only">
          cannot be opened: it was saved with {view.unreadable.join(", ")}, which this version no
          longer has
        </span>
        <RemoveButton name={view.name} onDelete={onDelete} deleting={deleting} />
      </span>
    );
  }

  return (
    <span
      className={
        showing
          ? "inline-flex h-8 items-center gap-1.5 rounded-full border border-primary bg-secondary px-3 text-sm font-medium"
          : "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm"
      }
    >
      <button
        type="button"
        onClick={onApply}
        aria-current={showing ? "true" : undefined}
        className="inline-flex items-center gap-1.5"
      >
        <Bookmark aria-hidden className="size-3.5" />
        {view.name}
      </button>
      <RemoveButton name={view.name} onDelete={onDelete} deleting={deleting} />
    </span>
  );
}

/**
 * No confirmation, deliberately.
 *
 * The product asks before deleting a job and three kinds of career record,
 * and the rule that decides which is whether anything is destroyed beyond
 * what the row shows. A view holds no data of its own: a name and a filter
 * combination, both rebuildable from the screen it was saved from.
 */
function RemoveButton({
  name,
  onDelete,
  deleting,
}: {
  name: string;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={`Delete the view ${name}`}
      disabled={deleting}
      onClick={onDelete}
      className="text-muted-foreground hover:text-foreground"
    >
      <X aria-hidden className="size-3.5" />
    </button>
  );
}

/**
 * The query without the reader's position in it.
 *
 * `page` is dropped because a view is a question and page four is not part of
 * one. Empty strings go with it: the filter selects express "no filter" as
 * `""`, and storing that would save a view asking for jobs whose work mode is
 * the empty string.
 */
export function comparable(query: JobListQuery): SavedViewFilters {
  const { page: _page, ...rest } = query;
  return Object.fromEntries(
    Object.entries(rest).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  ) as SavedViewFilters;
}

/** Whether two filter sets ask the same thing. */
function sameQuestion(a: SavedViewFilters, b: SavedViewFilters): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    if (a[key as keyof SavedViewFilters] !== b[key as keyof SavedViewFilters]) return false;
  }
  return true;
}

/** The default list: everything, newest first, unarchived. */
function isEverything(filters: SavedViewFilters): boolean {
  const meaningful = Object.entries(filters).filter(
    ([key, value]) =>
      !(
        (key === "sort" && value === "NEWEST") ||
        (key === "archived" && value === "ACTIVE") ||
        key === "page_size"
      ),
  );
  return meaningful.length === 0;
}
