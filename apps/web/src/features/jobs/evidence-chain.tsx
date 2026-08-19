"use client";

import {
  EVIDENCE_TYPE_LABELS,
  IMPORTANCE_LABELS,
  MATCH_STATUS_LABELS,
  REQUIREMENT_TYPE_LABELS,
  type MatchEvidence,
  type MatchItem,
} from "@jip/shared-types";
import type { ReactNode } from "react";

import {
  COLUMN_FOR_STATUS,
  VERDICT_ICONS,
  VERDICT_TEXT,
  shortName,
} from "@/features/jobs/match-axes";

/**
 * Why one requirement got the verdict it got, drawn as a chain.
 *
 * Four links, in the order the reasoning actually ran: the posting's sentence,
 * our reading of it, what we found on file, and where that left it. The form is
 * the argument. A verdict that appears beside its evidence invites the reading
 * that the two were produced together; a verdict at the end of a numbered chain
 * says which step produced it and, more usefully, which step to disagree with.
 *
 * Link 1 and link 2 are the whole reason this is not one paragraph.
 * `docs/08-ui-ux.md` requires our interpretation to be visibly distinct from
 * what the source said, so the quote is set in the foreground behind a rule and
 * the reading is set muted and labelled as a reading. They never share a
 * weight, and neither is ever rendered without the other.
 */
export function EvidenceChain({
  item,
  position,
  total,
  analysisVersion,
  onNext,
}: {
  item: MatchItem | null;
  /** Which requirement this is, in the posting's order. 1-based. */
  position: number;
  total: number;
  analysisVersion: number | null;
  onNext: () => void;
}) {
  if (!item) {
    return (
      <section
        aria-labelledby="evidence-chain-heading"
        className="flex min-h-0 flex-col rounded-xl border bg-card"
      >
        <div className="px-5 py-5">
          <h3 id="evidence-chain-heading" className="text-lg font-semibold">
            The evidence
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Pick a requirement to see the posting&apos;s own words, how we read them, and what in
            your profile answered.
          </p>
        </div>
      </section>
    );
  }

  const column = COLUMN_FOR_STATUS[item.status];
  const Icon = VERDICT_ICONS[column.tone];
  const requirement = item.requirement;

  return (
    <section
      aria-labelledby="evidence-chain-heading"
      className="flex min-h-0 flex-col rounded-xl border bg-card"
    >
      <header className="flex items-start justify-between gap-3 border-b px-5 pb-3.5 pt-5">
        <div className="min-w-0">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Requirement {position} of {total}
          </p>
          <h3 id="evidence-chain-heading" className="mt-2 text-lg font-semibold">
            {shortName(item)}
          </h3>
          {requirement && (
            <p className="mt-1 text-xs text-muted-foreground">
              {REQUIREMENT_TYPE_LABELS[requirement.requirement_type] ??
                requirement.requirement_type}{" "}
              &middot; {IMPORTANCE_LABELS[requirement.importance]} &middot;{" "}
              {requirement.explicitness === "EXPLICIT"
                ? "Stated in the posting"
                : "Inferred from the posting"}
            </p>
          )}
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold">
          <Icon aria-hidden className={`size-3.5 ${VERDICT_TEXT[column.tone]}`} />
          {MATCH_STATUS_LABELS[item.status]}
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-5 pb-5 pt-4">
        <ol className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-3">
          <Link n={1} title="What the posting said" last={false}>
            {requirement ? (
              <>
                <blockquote className="mt-2.5 border-l-2 border-foreground pl-3.5 text-sm font-medium leading-relaxed">
                  {requirement.source_text}
                </blockquote>
                <p className="mt-2 text-xs leading-snug text-foreground-faint">
                  The posting&apos;s own words, unedited.
                </p>
              </>
            ) : (
              /* Not a silent omission and not a placeholder quote. An empty
                 blockquote would read as a posting that said nothing, which is
                 a claim about the posting rather than about our records. */
              <p className="mt-2.5 text-sm text-muted-foreground">
                The wording behind this requirement is not on file, so there is nothing to quote.
              </p>
            )}
          </Link>

          <Link n={2} title="How we read it" last={false}>
            <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">
              {requirement
                ? `Read as: ${requirement.normalized_text}`
                : "Our reading of this requirement is not on file."}
            </p>
            <p className="mt-2 text-xs leading-snug text-foreground-faint">
              Our reading of the posting, not the posting.
              {requirement && (
                <>
                  {" "}
                  Confidence <span className="font-mono">{requirement.confidence}</span>
                </>
              )}
              {analysisVersion !== null && (
                <>
                  {" "}
                  &middot; reading <span className="font-mono">v{analysisVersion}</span>
                </>
              )}
            </p>
          </Link>

          <Link n={3} title="What we found in your profile" last={false}>
            {item.evidence.length > 0 ? (
              <ul className="mt-2.5 space-y-2">
                {item.evidence.map((ref) => (
                  <EvidenceCard key={ref.id} evidence={ref} />
                ))}
              </ul>
            ) : (
              <p className="mt-2.5 text-sm text-muted-foreground">
                Nothing in your profile speaks to this. That is a statement about what is on file,
                not about what you have done.
              </p>
            )}
          </Link>

          <Link n={4} title="Where that leaves it" last>
            <p className="mt-2.5 flex items-center gap-2 text-sm font-semibold">
              <Icon aria-hidden className={`size-3.5 ${VERDICT_TEXT[column.tone]}`} />
              {MATCH_STATUS_LABELS[item.status]}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{item.explanation}</p>
            <p className="mt-2 text-xs leading-snug text-foreground-faint">
              Confidence <span className="font-mono">{item.confidence}</span> &middot; weight{" "}
              <span className="font-mono">{item.weight}</span>
              {column.unanswered && " — excluded from the figure rather than counted against it"}
            </p>
            {total > 1 && (
              <button
                type="button"
                onClick={onNext}
                className="mt-4 h-9 rounded-lg border px-3.5 text-sm font-medium hover:bg-muted"
              >
                Next requirement
              </button>
            )}
          </Link>
        </ol>
      </div>
    </section>
  );
}

/** One link: its number, its rule down to the next, and its content. */
function Link({
  n,
  title,
  last,
  children,
}: {
  n: number;
  title: string;
  last: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <span
        aria-hidden
        className="flex size-5 items-center justify-center rounded-full border bg-background font-mono text-xs text-muted-foreground"
      >
        {n}
      </span>
      <li className={last ? "" : "pb-5"}>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{title}</p>
        {children}
      </li>
      {!last && (
        <>
          {/* The rule that makes it a chain rather than four cards. Decorative
              on purpose: the numbers already carry the sequence for anyone
              reading the markup rather than looking at it. */}
          <div aria-hidden className="flex justify-center">
            <span className="h-full w-px bg-border" />
          </div>
          <div />
        </>
      )}
    </>
  );
}

function EvidenceCard({ evidence }: { evidence: MatchEvidence }) {
  const confirmed =
    evidence.verification_status === "USER_CONFIRMED" ||
    evidence.verification_status === "EVIDENCE_BACKED";

  return (
    <li className="rounded-lg border px-3.5 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{evidence.label}</p>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">
          {EVIDENCE_TYPE_LABELS[evidence.evidence_type] ?? evidence.evidence_type}
        </span>
      </div>
      {evidence.detail && (
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{evidence.detail}</p>
      )}
      {/* Always stated, both ways round. A card that only spoke up when
          something was unconfirmed would leave the reader working out which
          silence meant what, and inferred data must never be able to pass for
          a fact the user stood behind. */}
      <p
        className={
          confirmed ? `mt-2 text-xs ${VERDICT_TEXT.strong}` : "mt-2 text-xs text-muted-foreground"
        }
      >
        {confirmed ? "Confirmed by you" : "Not yet confirmed by you"}
      </p>
    </li>
  );
}
