import { cva, type VariantProps } from "class-variance-authority";
import { Ban, Info } from "lucide-react";
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
 *
 * `refusal` has no callers, and neither does `CalloutLabel` below it. Both were
 * built for cases the product does have — a blocked URL, a blocked suggestion —
 * and neither was adopted when those were built. Recorded rather than deleted
 * or wired: which panel is a refusal rather than a caution is a product
 * judgement, and the two cases it names now render as cautions in two different
 * colours.
 */
const calloutVariants = cva("flex gap-3 rounded-md p-3 text-sm", {
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

/**
 * An icon per tone, and the reason it is here rather than left to callers.
 *
 * It was left to callers, and the result is what a pass looking for this finds:
 * **three panels in the app were hand-rolled copies of a Callout, and every one
 * of them added an icon.** `insights.tsx` wrote out the caution classes
 * verbatim to get an `Info` beside them; `job-tailoring.tsx` did the same in
 * destructive. People were not working around the component carelessly — they
 * were working around a tone that was weaker than the one they needed.
 *
 * `StateCard` had already settled this for its error state, which carries an
 * icon and a border and `role="alert"` together. A tone that is a hue and
 * nothing else asks the reader to have noticed a colour.
 *
 * `note` gets none on purpose. It is a neutral aside and an icon would give it
 * a temperature it does not have.
 */
const TONE_ICONS = {
  note: null,
  caution: Info,
  refusal: Ban,
} as const;

export function Callout({
  className,
  tone,
  children,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof calloutVariants>) {
  const Icon = TONE_ICONS[tone ?? "note"];

  return (
    <div className={cn(calloutVariants({ tone }), className)} {...props}>
      {Icon && <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
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
