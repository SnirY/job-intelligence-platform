import type { ReactNode } from "react";

/**
 * A column at a reading measure, inside a page that is wider than one.
 *
 * `/jobs/[jobId]` grew to `max-w-[1600px]` for the match workspace, and prose
 * does not want the width: a description set across 1600px is a line nobody can
 * track back from. So the page stops capping and each panel says what it needs.
 *
 * Shared rather than local to the page because the requirement list now makes
 * the same decision one level down — it leaves the column while the analysis
 * either side of it stays inside. Two callers, one measure.
 */
export function Reading({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-4xl space-y-6">{children}</div>;
}
