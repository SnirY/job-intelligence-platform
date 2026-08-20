"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/**
 * A delete that asks first, for the career records where asking is warranted.
 *
 * Warranted is a real line and not every row is over it. F29 was fixed on the
 * job delete with an argument that applies here too: a product that asks "are
 * you sure?" about everything has taught people to click through the one
 * question that mattered. Blanket-applying this component would be the same
 * mistake in the shape of a fix.
 *
 * The test is whether deleting destroys **composed prose or rows that hang off
 * it**, rather than facts the row already shows:
 *
 * - **Experience** qualifies. The list renders title, company and dates; the
 *   achievements and the description are only in the edit form, and
 *   `experience_achievements` cascades. That is paragraphs somebody wrote,
 *   invisible from the button that removes them, and the section's own
 *   description calls it *"the evidence a match traces back to"*.
 * - **Project** qualifies, for the same reason: summary, description and links
 *   are not in the row.
 * - **Skill** qualifies because `skill_evidence` cascades — the reasons a user
 *   typed for how they know something, which live behind a panel that is
 *   usually closed.
 *
 * - **Education**, **certifications** and **target roles** do not. Every field
 *   is a fact the row is already showing, nothing cascades off them, and
 *   retyping one takes as long as reading a dialog about it.
 * - Neither does a single evidence line, or a link in an unsaved form.
 *
 * Counts come from data the list already holds. Nothing here fetches to fill a
 * sentence, and where a number is not free the sentence does without one
 * rather than hedging — see the `consequence` note on `ConfirmDialog`.
 */
export function DeleteRecordButton({
  label,
  title,
  consequence,
  pending,
  onDelete,
}: {
  /** The accessible name of the button, e.g. "Remove Python". */
  label: string;
  /** The dialog's question. */
  title: string;
  consequence: ReactNode;
  pending: boolean;
  onDelete: () => void;
}) {
  const [asking, setAsking] = useState(false);

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={label}
        disabled={pending}
        onClick={() => setAsking(true)}
      >
        <Trash2 aria-hidden className="size-4" />
      </Button>

      <ConfirmDialog
        open={asking}
        title={title}
        consequence={consequence}
        confirmLabel="Delete"
        pending={pending}
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false);
          onDelete();
        }}
      />
    </>
  );
}

/** "3 achievements" / "1 achievement", and nothing at all for none. */
export function countOf(n: number, singular: string, plural = `${singular}s`): string | null {
  if (n <= 0) return null;
  return `${n} ${n === 1 ? singular : plural}`;
}
