"use client";

import { IMPORT_METHOD_LABELS, type JobImportMethod, type JobStatus } from "@jip/shared-types";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * What is happening to a job, in the user's terms.
 *
 * `RAW` and `ANALYZED` get no badge. They are the ordinary resting states of a
 * saved job, and a badge on every row would be noise that makes the states
 * worth noticing invisible. `docs/08-ui-ux.md` asks for calm over dense.
 *
 * The two failure states read differently on purpose: one needs the user to
 * supply text, the other needs nothing from them but a retry.
 */
export function JobStatusBadge({ status }: { status: JobStatus }) {
  if (status === "FETCHING") {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 aria-hidden className="size-3 animate-spin" />
        Reading the page
      </Badge>
    );
  }

  if (status === "PARSING" || status === "ANALYZING") {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 aria-hidden className="size-3 animate-spin" />
        Analysing
      </Badge>
    );
  }

  if (status === "FAILED") {
    return (
      <Badge variant="destructive" className="gap-1">
        {/* Never colour alone — docs/08-ui-ux.md. The icon and the word carry
            the meaning for anyone who cannot distinguish the colour. */}
        <AlertTriangle aria-hidden className="size-3" />
        Needs a description
      </Badge>
    );
  }

  if (status === "ANALYSIS_FAILED") {
    return (
      <Badge variant="outline" className="gap-1">
        <AlertTriangle aria-hidden className="size-3" />
        Analysis failed
      </Badge>
    );
  }

  return null;
}

/** How the job arrived. Quiet, because it matters only when it matters. */
export function ImportMethodBadge({ method }: { method: JobImportMethod }) {
  return <Badge variant="outline">{IMPORT_METHOD_LABELS[method]}</Badge>;
}
