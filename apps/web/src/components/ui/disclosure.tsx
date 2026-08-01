"use client";

import { ChevronRight } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A control that opens something in place, and looks like one at rest.
 *
 * DEV-029. Both the analysis panel and the match panel had grown their own
 * version of this as bare text — grey, small, underlined only on hover. The
 * match panel's read `Why? (1)`, and the person who commissioned the evidence
 * drawer could not find it. A count in parentheses reads as a footnote marker,
 * not as a promise of content behind a click.
 *
 * The evidence trail is the product's central claim: every verdict traceable
 * to something the user wrote, so the score is checkable rather than an
 * oracle. Unreachable, it is the oracle it was designed not to be.
 *
 * So: a border and a background at rest, a chevron that turns as it opens, and
 * a label that says what is behind it. Shared rather than styled twice, since
 * two copies were how the two panels came to disagree about how discoverable
 * this needed to be.
 */
export function Disclosure({
  open,
  onToggle,
  label,
  openLabel,
  count,
  icon,
  className,
}: {
  open: boolean;
  onToggle: () => void;
  /** Shown when closed. Say what opens, not that something does. */
  label: string;
  /** Shown when open. Defaults to "Hide". */
  openLabel?: string;
  /** Rendered as its own chip. Says how much is behind the click. */
  count?: number;
  /** Optional leading icon, sized by the caller's `size-3`. */
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={cn(
        "mt-2 inline-flex items-center gap-1.5 rounded-md border px-2 py-1",
        "text-xs font-medium text-foreground transition-colors",
        "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <ChevronRight
        aria-hidden
        className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")}
      />
      {icon}
      {open ? (openLabel ?? "Hide") : label}
      {!open && count !== undefined && (
        <span className="rounded bg-muted px-1 text-[10px] tabular-nums text-muted-foreground">
          {count}
        </span>
      )}
    </button>
  );
}
