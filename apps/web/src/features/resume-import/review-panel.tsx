"use client";

import {
  CANDIDATE_TYPE_LABELS,
  CANDIDATE_TYPE_ORDER,
  type ConfirmDecision,
  type Extraction,
  type ExtractionItem,
  type SourceDocument,
} from "@jip/shared-types";
import { AlertTriangle, Info, ScanLine } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirmExtraction } from "@/features/resume-import/api";
import {
  CandidateCard,
  type CandidateDecisionState,
} from "@/features/resume-import/candidate-card";
import { childrenOf, isDecided, topLevelOfType } from "@/features/resume-import/candidates";

interface ReviewPanelProps {
  /** Named in full rather than `document`, which would shadow the global. */
  sourceDocument: SourceDocument;
  extraction: Extraction;
}

/**
 * The review screen.
 *
 * Everything here is a proposal from a document, not profile data. Nothing
 * reaches the career profile until the user confirms, which is what
 * `docs/10-api-contracts.md` means by "AI extraction must not write verified
 * profile data directly".
 */
export function ReviewPanel({ sourceDocument, extraction }: ReviewPanelProps) {
  const confirm = useConfirmExtraction(sourceDocument.id);
  const pending = useMemo(
    () => extraction.items.filter((item) => !isDecided(item)),
    [extraction.items],
  );

  // Accept is the default, because a parse the user is reviewing is usually
  // mostly right. Every item is still individually changeable, and nothing is
  // sent until they press the button.
  const [decisions, setDecisions] = useState<Record<string, CandidateDecisionState>>(() =>
    Object.fromEntries(pending.map((item) => [item.id, { action: "ACCEPT" as const }])),
  );

  function decisionFor(item: ExtractionItem): CandidateDecisionState {
    return decisions[item.id] ?? { action: "ACCEPT" };
  }

  function setDecision(id: string, next: CandidateDecisionState) {
    setDecisions((current) => ({ ...current, [id]: next }));
  }

  function setAll(action: "ACCEPT" | "IGNORE") {
    setDecisions(Object.fromEntries(pending.map((item) => [item.id, { action }])));
  }

  function submit() {
    const payload: ConfirmDecision[] = pending.map((item) => {
      const decision = decisionFor(item);
      return decision.action === "EDIT" && decision.payload
        ? { item_id: item.id, action: "EDIT", payload: decision.payload }
        : { item_id: item.id, action: decision.action === "EDIT" ? "ACCEPT" : decision.action };
    });
    confirm.mutate(payload);
  }

  if (pending.length === 0) {
    return <AllReviewed extraction={extraction} />;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Review what we found</CardTitle>
          <CardDescription>
            These are proposals read from your document, not part of your profile yet. Accept, edit,
            or ignore each one — nothing is saved until you confirm.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {extraction.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border border-dashed p-3">
              {extraction.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-xs text-muted-foreground">
                  <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" size="sm" onClick={() => setAll("ACCEPT")}>
              Accept all
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setAll("IGNORE")}>
              Ignore all
            </Button>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Info aria-hidden className="size-3.5" />
              Read from {extraction.model} using {extraction.prompt_version}.
            </p>

            {/* Beside the model line, not above it as a warning. Where the text
              came from is provenance, in the same voice as which model read it
              — and the person confirming these proposals is the one who needs
              it. An icon as well as the words, because colour alone carries
              nothing for a reader who cannot see it (docs/08-ui-ux.md). */}
            {sourceDocument.text_source === "OCR" && (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ScanLine aria-hidden className="size-3.5" />
                Read from a scan of the pages
                {sourceDocument.ocr_confidence !== null &&
                  `, ${Math.round(sourceDocument.ocr_confidence)}% clear`}
                . Numbers and names are where a scan goes wrong.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {CANDIDATE_TYPE_ORDER.map((type) => {
        const items = topLevelOfType(pending, type);
        if (items.length === 0) return null;

        return (
          <Card key={type}>
            <CardHeader>
              <CardTitle className="text-base">{CANDIDATE_TYPE_LABELS[type]}</CardTitle>
              <CardDescription>
                {items.length} {items.length === 1 ? "proposal" : "proposals"} from your document.
              </CardDescription>
            </CardHeader>

            <CardContent>
              <ul className="space-y-3">
                {items.map((item) => {
                  const children = childrenOf(pending, item.id);
                  return (
                    <CandidateCard
                      key={item.id}
                      item={item}
                      decision={decisionFor(item)}
                      onChange={(next) => setDecision(item.id, next)}
                    >
                      {children.length > 0 && (
                        <ul className="space-y-2 pt-1">
                          {children.map((child) => (
                            <CandidateCard
                              key={child.id}
                              item={child}
                              nested
                              decision={decisionFor(child)}
                              onChange={(next) => setDecision(child.id, next)}
                            />
                          ))}
                        </ul>
                      )}
                    </CandidateCard>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        );
      })}

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-6">
          <Button type="button" disabled={confirm.isPending} onClick={submit}>
            {confirm.isPending ? "Saving…" : "Add to my profile"}
          </Button>
          <p aria-live="polite" className="text-sm">
            {confirm.isError && (
              <span className="text-destructive">
                Could not save those choices. Nothing was changed — try again.
              </span>
            )}
            {confirm.isSuccess && (
              <span className="text-muted-foreground">
                Added {confirm.data.created_count} to your profile.
              </span>
            )}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function AllReviewed({ extraction }: { extraction: Extraction }) {
  const accepted = extraction.items.filter(
    (item) => item.decision === "ACCEPTED" || item.decision === "EDITED",
  ).length;
  const ignored = extraction.items.filter((item) => item.decision === "IGNORED").length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Import complete</CardTitle>
        <CardDescription>You reviewed everything we found in this document.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>
          {accepted} {accepted === 1 ? "item was" : "items were"} added to your profile
          {ignored > 0 ? `, and ${ignored} ${ignored === 1 ? "was" : "were"} ignored.` : "."}
        </p>
        <p className="text-muted-foreground">
          Everything is on your career profile now, where you can keep editing it.
        </p>
      </CardContent>
    </Card>
  );
}
