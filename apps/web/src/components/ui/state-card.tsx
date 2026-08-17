import { AlertTriangle, Loader2 } from "lucide-react";
import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * The panel a screen shows instead of its content: still loading, or failed.
 *
 * Written once because it had been written seven times. `Panel`, `Notice` and
 * `Message` were separate local definitions in seven feature files — five of
 * them byte-identical — and the drift had already started: one grew a spinner,
 * one grew its own page heading. Seven copies of "something went wrong" is
 * seven places to fix a sentence, and the sentences are the part this product
 * protects.
 *
 * The two tones render differently on purpose. Every one of those copies drew
 * loading and error as the same paragraph in the same card, so a failure looked
 * exactly like a slow request. `docs/08-ui-ux.md` asks for the opposite — a
 * failure has to look like a failure — and the icon and the left border are
 * what carry that, since a colour alone carries nothing to a reader who cannot
 * see it.
 */
export function StateCard({
  tone = "loading",
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { tone?: "loading" | "error" }) {
  const failed = tone === "error";

  return (
    <Card
      className={cn(failed && "border-l-2 border-l-destructive", className)}
      /* Polite for loading, assertive for a failure: one is progress the reader
         can ignore, the other changed what is on the screen. */
      role={failed ? "alert" : "status"}
      aria-live={failed ? undefined : "polite"}
      {...props}
    >
      <CardContent className="flex items-start gap-3 p-6">
        {failed ? (
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
        ) : (
          <Loader2
            aria-hidden
            className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground"
          />
        )}
        <div className={cn("text-sm", failed ? "text-foreground" : "text-muted-foreground")}>
          {children}
        </div>
      </CardContent>
    </Card>
  );
}
