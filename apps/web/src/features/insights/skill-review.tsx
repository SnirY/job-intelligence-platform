"use client";

import {
  API_ROUTES,
  SKILL_CATEGORY_LABELS,
  type SkillCandidate,
  type SkillCategory,
} from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RefreshCw, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useApi } from "@/lib/use-api";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const queueKey = ["skill-candidates"] as const;

/**
 * The review queue for skill names the catalogue does not know.
 *
 * DEV-062. Lives on Insights rather than in the main navigation: this is
 * catalogue maintenance, not one of the seven user flows `docs/02` names, and
 * it belongs beside the demand list that already reports which skills the jobs
 * keep asking for and are not catalogued.
 */
export function SkillReview() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);

  const queue = useQuery({
    queryKey: queueKey,
    queryFn: () => api<SkillCandidate[]>(API_ROUTES.skillCandidates),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queueKey });
    // The demand and gap lists are computed from resolved requirements, so a
    // decision here changes them. Leaving them cached would show the reviewer
    // a page that disagrees with the decision they just made.
    void queryClient.invalidateQueries({ queryKey: ["insights"] });
    setEditing(null);
  };

  const refresh = useMutation({
    mutationFn: () =>
      api<SkillCandidate[]>(`${API_ROUTES.skillCandidates}/refresh`, { method: "POST" }),
    onSuccess: invalidate,
  });

  const decide = useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: string; body: unknown }) =>
      api<SkillCandidate>(`${API_ROUTES.skillCandidates}/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });

  const items = queue.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Skill names needing a decision</CardTitle>
        <CardDescription>
          Technologies your saved postings named that the shared catalogue could not resolve. Until
          one is decided, a job asking for it cannot be matched against your profile.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            <RefreshCw aria-hidden className="size-4" />
            {refresh.isPending ? "Checking…" : "Check for new names"}
          </Button>
          <p aria-live="polite" className="text-sm text-destructive">
            {refresh.isError && "Could not rebuild the queue."}
            {decide.isError && "Could not save that decision."}
          </p>
        </div>

        {queue.isError ? (
          <p className="text-sm text-destructive">Could not load the queue.</p>
        ) : queue.isPending || !items ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing waiting. Every technology your postings named resolves to a catalogue entry.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {items.map((candidate) => (
              <li key={candidate.id} className="space-y-3 p-3">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{candidate.display_name}</p>
                    {/* The sentence, not just the name. A reviewer deciding
                        "CAN" is otherwise guessing at a three-letter string
                        that is also an ordinary English word. */}
                    {candidate.example_source_text && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        “{candidate.example_source_text}”
                      </p>
                    )}
                    {candidate.example_job_title && (
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {candidate.example_job_title}
                      </p>
                    )}
                  </div>

                  <Badge variant="secondary">
                    {candidate.occurrences} {candidate.occurrences === 1 ? "posting" : "postings"}
                  </Badge>

                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-expanded={editing === candidate.id}
                    onClick={() => setEditing(editing === candidate.id ? null : candidate.id)}
                  >
                    <Check aria-hidden className="size-4" />
                    Add to catalogue
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Not a skill: ${candidate.display_name}`}
                    disabled={decide.isPending}
                    onClick={() => setRejecting(candidate.id)}
                  >
                    <X aria-hidden className="size-4" />
                    Not a skill
                  </Button>

                  <ConfirmDialog
                    open={rejecting === candidate.id}
                    title={`Record that “${candidate.display_name}” is not a skill?`}
                    confirmLabel="Not a skill"
                    pending={decide.isPending}
                    onCancel={() => setRejecting(null)}
                    onConfirm={() => {
                      setRejecting(null);
                      decide.mutate({ id: candidate.id, action: "reject", body: {} });
                    }}
                    consequence={
                      <>
                        {/* The strongest case for a confirmation in this
                            product, and it had the weakest control. Rejecting
                            is remembered on purpose — this module's own note
                            says a rejected candidate "stays rejected however
                            many further postings use it", which is the point
                            of storing rejections at all. There is no route
                            that reopens one: `_pending` refuses anything that
                            is not still pending. */}
                        <p>
                          The name will not be proposed again, however many postings use it, and
                          there is no way to undo this from here.
                        </p>
                        <p>
                          {/* Named because the catalogue is not this account's.
                              Every other rule about destructive actions in this
                              product concerns the user's own data; this one
                              does not. */}
                          The catalogue is shared with every account, so this decides the name for
                          everyone — not only for you.
                        </p>
                        <p>
                          It was named in{" "}
                          <span className="font-medium text-foreground">
                            {candidate.occurrences}{" "}
                            {candidate.occurrences === 1 ? "posting" : "postings"}
                          </span>{" "}
                          you have saved.
                        </p>
                      </>
                    }
                  />
                </div>

                {editing === candidate.id && (
                  <AddForm
                    candidate={candidate}
                    pending={decide.isPending}
                    onSubmit={(body) =>
                      decide.mutate({ id: candidate.id, action: "accept-new", body })
                    }
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

interface AddFormProps {
  candidate: SkillCandidate;
  pending: boolean;
  onSubmit: (body: { category: SkillCategory; canonical_name: string }) => void;
}

/** Name and category for a new catalogue entry. */
function AddForm({ candidate, pending, onSubmit }: AddFormProps) {
  const [name, setName] = useState(candidate.display_name);
  const [category, setCategory] = useState<SkillCategory>("OTHER");

  const blank = name.trim() === "";

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-md bg-muted/40 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (blank) return;
        onSubmit({ category, canonical_name: name.trim() });
      }}
    >
      <div className="min-w-0 flex-1 space-y-2">
        <Label htmlFor={`name-${candidate.id}`}>Catalogue name</Label>
        <Input
          id={`name-${candidate.id}`}
          value={name}
          maxLength={120}
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={`category-${candidate.id}`}>Category</Label>
        <Select
          id={`category-${candidate.id}`}
          value={category}
          onChange={(event) => setCategory(event.target.value as SkillCategory)}
        >
          {Object.entries(SKILL_CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      <Button type="submit" disabled={blank || pending}>
        {pending ? "Saving…" : "Add"}
      </Button>
    </form>
  );
}
