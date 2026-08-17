import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/*
 * The inline panel that qualifies whatever sits above it — not a card, and
 * deliberately lighter than one, because it is a note about content rather than
 * content of its own.
 *
 * Three tones, and the third is the one worth explaining. `refusal` is for a
 * settled fact the reader cannot act on: a permanently blocked URL, a
 * suggestion the tone check will not pass. It sits on `--surface-raised` rather
 * than in the caution colour, because caution asks the reader to do something
 * and there is nothing here to do. `docs/08-ui-ux.md` keeps a retry only where
 * a retry can work; this is the same rule wearing its visual clothes.
 */
const calloutVariants = cva("rounded-md p-3 text-sm", {
  variants: {
    tone: {
      note: "border text-muted-foreground",
      caution: "border border-notice/40 bg-notice/5 text-foreground",
      refusal: "bg-surface-raised text-surface-raised-foreground",
    },
  },
  defaultVariants: {
    tone: "note",
  },
});

export function Callout({
  className,
  tone,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof calloutVariants>) {
  return <div className={cn(calloutVariants({ tone }), className)} {...props} />;
}

/**
 * The small uppercase label that names a refusal — "Refused", "Blocked".
 *
 * Set in the mono face at the third text tier, which on dark is carried by
 * case, size and tracking rather than by lightness. See the note on
 * `--foreground-faint` in `globals.css`.
 */
export function CalloutLabel({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      className={cn(
        "font-mono text-xs font-medium uppercase tracking-[0.1em] opacity-65",
        className,
      )}
      {...props}
    />
  );
}

export { calloutVariants };
