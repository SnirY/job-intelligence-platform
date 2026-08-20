"use client";

import { useCallback, useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

/**
 * A confirmation for something that cannot be undone.
 *
 * F29, from the 2026-08-11 audit: delete was a ghost button, one click, no
 * dialog, no undo, no way back. It came up again while deciding that bulk
 * archive needs none of this — archive is reversible and delete is not, so a
 * confirmation belongs here and nowhere else. A product that asks "are you
 * sure?" about everything has taught people to click through the one question
 * that mattered.
 *
 * Which is why this takes `consequence` rather than a message. "Are you sure?"
 * transfers responsibility without transferring information; naming what goes
 * with the thing — the readings of the posting, the matches, the application
 * being tracked — is the difference between a speed bump and a decision. The
 * caller computes it from data already on screen.
 *
 * Three things about the focus, and each is a defect somewhere in this repo's
 * history. Focus enters on open and **returns to the opener on close**, which
 * is F31, recorded against the mobile drawer. Tab is trapped, because
 * `aria-modal` promises a screen reader that what is behind is unreachable and
 * a dialog that lets Tab run onto the page underneath makes that promise false.
 * And **the destructive button is never what opens focused** — a dialog that
 * arrives with Delete under the cursor has turned Enter into the thing it was
 * put there to prevent.
 */
export function ConfirmDialog({
  open,
  title,
  consequence,
  confirmLabel,
  onConfirm,
  onCancel,
  pending = false,
  alternative,
}: {
  open: boolean;
  title: string;
  /** What is destroyed, in the user's terms. Never a restatement of the title. */
  consequence: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
  /** The reversible thing to do instead, when there is one. */
  alternative?: { label: string; onSelect: () => void };
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();

  // Captured as it opens rather than on the click that opened it, so a caller
  // cannot forget to pass it.
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement as HTMLElement | null;
    // Queried rather than held by ref, so this does not depend on `Button`
    // forwarding one. What it must never resolve to is the destructive button.
    panelRef.current?.querySelector<HTMLElement>("[data-confirm-cancel]")?.focus();
  }, [open]);

  const cancel = useCallback(() => {
    onCancel();
    opener.current?.focus();
  }, [onCancel]);

  const confirm = useCallback(() => {
    onConfirm();
    opener.current?.focus();
  }, [onConfirm]);

  if (!open) return null;

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Escape is cancel, never confirm. The key people press when they are not
    // sure has to resolve the safe way.
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
      return;
    }

    if (event.key === "Tab") {
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 p-4"
      onClick={cancel}
    >
      <div
        ref={panelRef}
        /* alertdialog, not dialog. The role exists for exactly this — an
           interruption carrying a consequence — and it makes a screen reader
           announce the body rather than only the title. */
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        className="w-full max-w-md rounded-xl border bg-card p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId} className="text-base font-semibold">
          {title}
        </h2>

        <div id={bodyId} className="mt-2.5 space-y-2 text-sm text-muted-foreground">
          {consequence}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2.5">
          {alternative && (
            <Button
              type="button"
              variant="secondary"
              disabled={pending}
              onClick={() => {
                alternative.onSelect();
                opener.current?.focus();
              }}
              className="mr-auto"
            >
              {alternative.label}
            </Button>
          )}

          <Button data-confirm-cancel type="button" variant="outline" onClick={cancel}>
            Cancel
          </Button>

          <Button type="button" variant="destructive" disabled={pending} onClick={confirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
