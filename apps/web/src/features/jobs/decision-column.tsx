"use client";

import { MATCH_STATUS_LABELS, type MatchItem } from "@jip/shared-types";
import Link from "next/link";

import {
  COLUMN_FOR_STATUS,
  VERDICT_COLUMNS,
  VERDICT_ICONS,
  VERDICT_TEXT,
  countByColumn,
  shortName,
  type VerdictTone,
} from "@/features/jobs/match-axes";

/**
 * The whole posting as one row of cells, in the order it was written.
 *
 * A navigator, not a summary. The list's strip is a proportional bar and is
 * `aria-hidden` on purpose — it says how a job is shaped and nothing more. This
 * one is a cell per requirement, and every cell is a control, because on a
 * screen where the field is arranged by meaning the posting's own sequence has
 * nowhere else to live.
 *
 * Verdict is carried three ways: colour, height, and fill. `docs/08-ui-ux.md`
 * forbids colour alone, and in a shape this small an icon does not fit, so the
 * redundancy is geometric — how tall the cell stands for how much of the
 * requirement was answered, solid against outlined for whether the answer was
 * about your record or about ours. The words are in the legend beneath and in
 * every cell's accessible name; none of them are carried by hover, which fails
 * on touch and on keyboard both.
 */
export function CoverageStrip({
  items,
  selectedId,
  onSelect,
}: {
  items: MatchItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const ordered = [...items].sort((a, b) => a.source_order - b.source_order);
  if (ordered.length === 0) return null;

  const counts = countByColumn(items);

  return (
    <section aria-labelledby="coverage-heading" className="rounded-xl border bg-card p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 id="coverage-heading" className="text-sm font-medium">
          Coverage
        </h3>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">{ordered.length}</span> requirements
        </p>
      </div>

      <ul className="mt-3.5 flex h-8 items-end gap-px">
        {ordered.map((item, index) => (
          <li key={item.id} className="min-w-0 flex-1">
            <Cell
              item={item}
              position={index + 1}
              total={ordered.length}
              selected={item.id === selectedId}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>

      {/* The key. The recorded rule is that a chart's labels are never carried
          by hover, so every lane is named here in full whether or not it has
          anything in it — the counts are the reading, and a zero is a reading
          too. */}
      <dl className="mt-3.5 space-y-1.5">
        {VERDICT_COLUMNS.map((column) => {
          const Icon = VERDICT_ICONS[column.tone];
          return (
            <div key={column.key} className="grid grid-cols-[14px_1fr_auto] items-center gap-2.5">
              <Icon aria-hidden className={`size-3.5 ${VERDICT_TEXT[column.tone]}`} />
              <dt className="text-xs">{column.label}</dt>
              <dd className="font-mono text-xs text-muted-foreground">{counts[column.key] ?? 0}</dd>
            </div>
          );
        })}
      </dl>

      <p className="mt-3.5 text-xs leading-relaxed text-foreground-faint">
        In the order the posting wrote them. Pick one to open it.
      </p>
    </section>
  );
}

/**
 * How tall a cell stands, and whether it is filled.
 *
 * Height is how much of the requirement was answered. Fill separates a finding
 * about your record from a finding about ours: a gap is solid because it is a
 * real absence, and nothing-on-file is hollow because it is a statement about
 * what we hold. That pairing matters most at the two short heights, where
 * colour is doing the work on eight pixels.
 */
const CELL_SHAPE: Record<VerdictTone, string> = {
  strong: "h-full bg-verdict-strong",
  ok: "h-2/3 bg-verdict-partial",
  transfer: "h-2/3 border border-verdict-transfer",
  gap: "h-1/3 bg-verdict-gap",
  blocked: "h-1/3 bg-verdict-blocked",
  neutral: "h-1/3 border border-muted-foreground",
};

function Cell({
  item,
  position,
  total,
  selected,
  onSelect,
}: {
  item: MatchItem;
  position: number;
  total: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const column = COLUMN_FOR_STATUS[item.status];

  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      aria-pressed={selected}
      aria-label={`Requirement ${position} of ${total}: ${shortName(item)} — ${
        MATCH_STATUS_LABELS[item.status]
      }`}
      className="flex h-8 w-full items-end"
    >
      <span
        aria-hidden
        className={`w-full rounded-sm ${CELL_SHAPE[column.tone]} ${
          selected ? "ring-2 ring-primary ring-offset-1 ring-offset-card" : ""
        }`}
      />
    </button>
  );
}

/**
 * The one thing worth doing next, when there is one.
 *
 * Derived, never invented. Each branch is a count of rows already on this
 * screen, and the card does not appear at all when none of them is above zero —
 * a "next move" panel that always finds something to say is a panel nobody
 * believes the third time.
 *
 * What it deliberately does not say is that acting will raise the figure. It
 * might not. Confirming a skill is a statement about your record that happens
 * to be visible from here, and offering it as a lever on this job's number
 * would be inviting someone to edit their history for a score.
 */
export function NextMove({
  items,
  onSelect,
}: {
  items: MatchItem[];
  onSelect: (id: string) => void;
}) {
  // Distinct career rows, not evidence rows: one skill cited behind three
  // requirements is one thing to confirm, and counting it three times would
  // promise more work than exists.
  const unconfirmed = new Set(
    items
      .filter((item) => {
        const column = COLUMN_FOR_STATUS[item.status];
        return column?.tone === "ok" || column?.tone === "transfer";
      })
      .flatMap((item) =>
        item.evidence
          .filter(
            (ref) =>
              ref.verification_status !== "USER_CONFIRMED" &&
              ref.verification_status !== "EVIDENCE_BACKED",
          )
          .map((ref) => ref.entity_id),
      ),
  );

  const unanswered = items.filter((item) => COLUMN_FOR_STATUS[item.status]?.unanswered);

  if (unconfirmed.size > 0) {
    return (
      <Move
        heading={`Confirm ${unconfirmed.size} ${unconfirmed.size === 1 ? "thing" : "things"} you already have.`}
        body="Those verdicts rest on entries we read from your resume and you have not confirmed. Confirming them is a statement about your record, not about this job."
        href="/career-profile"
        cta="Open your profile"
      />
    );
  }

  if (unanswered.length > 0) {
    const first = unanswered[0];
    return (
      <Move
        heading={`${unanswered.length} ${
          unanswered.length === 1 ? "requirement has" : "requirements have"
        } nothing on file.`}
        body="Not a low score — no figure at all. They are left out of the arithmetic rather than counted against you, so filling them in changes what we can say, not what we have said."
        href="/career-profile"
        cta="Open your profile"
        onOpen={first ? () => onSelect(first.id) : undefined}
      />
    );
  }

  return null;
}

function Move({
  heading,
  body,
  href,
  cta,
  onOpen,
}: {
  heading: string;
  body: string;
  href: string;
  cta: string;
  onOpen?: () => void;
}) {
  return (
    <section
      aria-labelledby="next-move-heading"
      className="rounded-xl bg-surface-raised p-5 text-surface-raised-foreground"
    >
      <p className="font-mono text-xs uppercase tracking-wider opacity-65">Next move</p>
      <h3 id="next-move-heading" className="mt-2.5 text-base font-semibold leading-snug">
        {heading}
      </h3>
      <p className="mt-2 text-sm leading-relaxed opacity-85">{body}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Link
          href={href}
          className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
        >
          {cta}
        </Link>
        {onOpen && (
          <button
            type="button"
            onClick={onOpen}
            className="text-sm font-medium underline underline-offset-4"
          >
            Show me the first one
          </button>
        )}
      </div>
    </section>
  );
}
