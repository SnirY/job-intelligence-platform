"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * The focus contract every overlay in this product owes, in one place.
 *
 * Three overlays exist — the confirm dialog, the command palette, and the
 * mobile drawer — and until now two of them implemented this by hand and the
 * third implemented none of it. **The third is the one F31 was recorded
 * against.** That entry is cited in both hand-written copies as the reason they
 * restore focus, and the drawer it describes still opened with `aria-modal` and
 * no trap, no entry, no restore and no Escape.
 *
 * Which is the argument for a hook rather than a third copy. A contract that
 * has to be re-typed is a contract two thirds of the codebase keeps.
 *
 * Four rules, and each one is a defect somebody has already had:
 *
 * **Focus enters.** An overlay that opens without taking focus leaves a
 * keyboard reader at the top of the document, reading the page it just covered.
 *
 * **Tab is trapped.** `aria-modal="true"` promises a screen reader that what is
 * behind is unreachable. Tab walking out of the panel makes that promise false,
 * which is worse than never making it — the reader is told they are somewhere
 * they are not.
 *
 * **Escape dismisses.** The key somebody presses when they are unsure has to
 * resolve the safe way.
 *
 * **Focus returns to whatever opened it.** Otherwise closing drops the reader
 * back at the start of the document with no memory of where they were. F31.
 */
export function useModalFocus<T extends HTMLElement>({
  open,
  onDismiss,
  initialFocus,
}: {
  open: boolean;
  onDismiss: () => void;
  /**
   * A selector for what should hold focus on open, resolved inside the panel.
   *
   * Given rather than inferred, because "the first focusable thing" is the
   * wrong answer where it matters most: a destructive dialog opening with
   * Delete under the cursor has turned Enter into the thing it exists to
   * prevent.
   */
  initialFocus?: string;
}) {
  const panelRef = useRef<T>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    opener.current = document.activeElement as HTMLElement | null;

    const panel = panelRef.current;
    if (!panel) return;

    const target = initialFocus
      ? panel.querySelector<HTMLElement>(initialFocus)
      : focusable(panel)[0];

    // The panel itself as a last resort, so focus lands inside even when the
    // overlay is a message with nothing to operate.
    (target ?? panel).focus();
  }, [open, initialFocus]);

  const dismiss = useCallback(() => {
    onDismiss();
    opener.current?.focus();
  }, [onDismiss]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }

      if (event.key !== "Tab") return;

      const stops = focusable(panelRef.current);
      if (stops.length === 0) return;

      const first = stops[0];
      const last = stops[stops.length - 1];

      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
    },
    [dismiss],
  );

  /** Call after any close that is not a dismissal — a confirm, a navigation. */
  const restoreFocus = useCallback(() => {
    opener.current?.focus();
  }, []);

  return { panelRef, onKeyDown, dismiss, restoreFocus };
}

function focusable(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
}
