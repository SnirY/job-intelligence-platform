"use client";

import type { ConcernConfidence, PostingConcern } from "@jip/shared-types";
import { CircleAlert, Info, TriangleAlert } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { usePostingConcerns } from "@/features/jobs/api";

/**
 * What we noticed about the posting, beside the match and never inside it.
 *
 * **The rule this component exists to render correctly:** a concern about the
 * listing never changes the match score, and the screen has to keep the two
 * readable as separate answers. A role can be an excellent match and a
 * suspicious posting at the same time — folding either into the other would
 * leave a reader unable to tell whether a low figure meant "you do not fit" or
 * "we do not trust this listing".
 *
 * So this is its own card with its own heading, it never sits above the match
 * panel, and it shows no number of any kind.
 *
 * **Nothing renders when no concern was raised**, and that is deliberate. An
 * empty result means no rule fired, which is not the same as "this posting is
 * trustworthy" — and a green tick saying "no concerns" would assert exactly the
 * thing the rules cannot support. Invariant 14 in a new place: absence of a
 * finding is a fact about our rules, not a claim about the world.
 */
export function PostingConcerns({ jobId }: { jobId: string }) {
  const concerns = usePostingConcerns(jobId);

  const rows = concerns.data?.concerns ?? [];
  // Silent on loading and on failure too. This panel is supplementary, and a
  // spinner or an error card here would draw the eye to the one part of the
  // screen that has nothing to say.
  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">About this posting</CardTitle>
        <CardDescription>
          What we noticed about the listing itself. This does not affect your match — a role can fit
          you well and still be worth a second look.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {rows.map((concern) => (
          <ConcernRow key={concern.type} concern={concern} />
        ))}
      </CardContent>
    </Card>
  );
}

function ConcernRow({ concern }: { concern: PostingConcern }) {
  const { Icon, label } = presentation(concern.confidence);

  return (
    <div className="flex gap-3">
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 space-y-1">
        {/* The label carries the confidence in words. Invariant 3: nothing is
          conveyed by colour alone, and these three levels are exactly the kind
          of distinction a palette would be asked to carry. */}
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="text-sm">{concern.summary}</p>
        {concern.evidence && (
          <blockquote className="border-l-2 pl-3 text-sm italic text-muted-foreground">
            {concern.evidence}
          </blockquote>
        )}
      </div>
    </div>
  );
}

/**
 * How each level is drawn and named.
 *
 * "Worth knowing" rather than "low risk": the observed level covers things like
 * a short posting, which is not a risk at all and must not be worded as one.
 */
function presentation(confidence: ConcernConfidence) {
  switch (confidence) {
    case "NEAR_CERTAIN":
      return { Icon: CircleAlert, label: "Serious" };
    case "SUSPICIOUS":
      return { Icon: TriangleAlert, label: "Unusual" };
    default:
      return { Icon: Info, label: "Worth knowing" };
  }
}
