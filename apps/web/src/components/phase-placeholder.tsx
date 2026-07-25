import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface PhasePlaceholderProps {
  title: string;
  /** The roadmap phase that will make this page functional. */
  phase: number;
  phaseName: string;
  /** What the page will do, described honestly in the future tense. */
  description: string;
}

/**
 * Stands in for a page whose phase has not arrived.
 *
 * It states plainly that nothing is built yet. It must never show sample rows,
 * placeholder charts, or invented counts: fake data is indistinguishable from a
 * broken feature, and it makes the product's progress impossible to read.
 */
export function PhasePlaceholder({ title, phase, phaseName, description }: PhasePlaceholderProps) {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-muted-foreground">{description}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Not built yet</CardTitle>
          <CardDescription>
            Arriving in Phase {phase} — {phaseName}.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <p>
            This page is intentionally empty. Showing example content here would make an unfinished
            feature look finished.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
