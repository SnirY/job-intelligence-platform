"use client";

import {
  careerSkillEvidenceRoute,
  type SkillEvidence,
  type SkillEvidenceCreate,
} from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCollection } from "@/features/career/use-collection";

/** Words the profile uses for evidence it collected rather than the user typed. */
const SOURCE_LABELS: Record<string, string> = {
  MANUAL: "You said",
  EDUCATION: "From your education",
  CERTIFICATION: "From a certification",
  RESUME: "From your resume",
  EXPERIENCE: "From a role",
  PROJECT: "From a project",
};

const MAX_NOTE = 500;

interface SkillEvidencePanelProps {
  skillId: string;
  skillName: string;
}

/**
 * "Why do you know this?" for one skill.
 *
 * DEV-054. Until the `skill_evidence` table existed the only way to show where
 * a skill came from was to attach it to a role or a project, so anything
 * learned on a course, in a competition, or on a thing built and never shipped
 * could be claimed and never evidenced — and the profile went on listing it as
 * a gap. This is where the user answers.
 *
 * Deliberately not a confirmation control. Adding a reason does not verify the
 * skill: `docs/05` reserves that for a decision the user makes about a claim,
 * and this is an explanation of one.
 */
export function SkillEvidencePanel({ skillId, skillName }: SkillEvidencePanelProps) {
  const { query, create, remove } = useCollection<SkillEvidence, SkillEvidenceCreate>(
    ["career", "skills", skillId, "evidence"],
    careerSkillEvidenceRoute(skillId),
  );
  const [note, setNote] = useState("");

  const trimmed = note.trim();
  const items = query.data;

  return (
    <div className="mt-2 space-y-3 rounded-md bg-muted/40 p-3">
      {query.error ? (
        <p className="text-sm text-destructive">Could not load your reasons for {skillName}.</p>
      ) : query.isPending || !items ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing here yet. A course, a competition, a thing you built — anything that shows where
          this came from counts, and it stops {skillName} being listed as a gap.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((evidence) => (
            <li key={evidence.id} className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm">{evidence.note}</p>
                <p className="text-xs text-muted-foreground">
                  {SOURCE_LABELS[evidence.source] ?? evidence.source}
                </p>
              </div>
              {/* Only the reasons the user typed are theirs to delete. The rest
                  are views of a role or a project and are removed by removing
                  that, which keeps one fact in one place. */}
              {evidence.source === "MANUAL" && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove this reason for ${skillName}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(evidence.id)}
                >
                  <Trash2 aria-hidden className="size-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (trimmed === "") return;
          create.mutate({ note: trimmed }, { onSuccess: () => setNote("") });
        }}
      >
        <div className="min-w-0 flex-1 space-y-2">
          <Label htmlFor={`evidence-${skillId}`}>Add a reason</Label>
          <Input
            id={`evidence-${skillId}`}
            value={note}
            maxLength={MAX_NOTE}
            placeholder="Built a compiler for it over a winter"
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <Button type="submit" variant="secondary" disabled={trimmed === "" || create.isPending}>
          <Plus aria-hidden className="size-4" />
          {create.isPending ? "Saving…" : "Add"}
        </Button>
      </form>

      <p aria-live="polite" className="text-sm text-destructive">
        {create.isError && "Could not save that reason."}
        {remove.isError && "Could not remove that reason."}
      </p>
    </div>
  );
}
