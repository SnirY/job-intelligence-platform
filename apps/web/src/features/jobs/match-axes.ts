import {
  IMPORTANCE_LABELS,
  MATCH_STATUS_LABELS,
  type MatchItem,
  type MatchStatus,
  type RequirementImportance,
} from "@jip/shared-types";
import {
  AlertOctagon,
  ArrowLeftRight,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  MinusCircle,
} from "lucide-react";

/**
 * The two axes the requirement field is laid out on.
 *
 * Down: how much the posting insisted, from the requirement. Across: what the
 * profile answered, from the item. Position is the whole point of the form —
 * a chip's place carries meaning before its label is read — which forces two
 * rules on everything here.
 *
 * **Neither axis ever loses a lane.** An empty Blocker column is the best news
 * this screen can deliver, and hiding it removes the one column whose
 * emptiness is the message. Lanes that came and went per job would also make
 * two jobs incomparable: the same position would mean different things on
 * different screens and the form would stop being learnable. A sparse job
 * keeps its axes and reports what it found.
 *
 * **A lane holds one kind of verdict.** `docs/05-ai-and-matching.md` is
 * explicit that GAP, NO_EVIDENCE and UNKNOWN are three different things and
 * must not be conflated: a gap is a real absence, nothing on file is a claim
 * about our information, and check-yourself means the question cannot be
 * answered by arithmetic at all. Three lanes, therefore, not one called "no".
 * STRONG_MATCH and MATCH do share one, because they are two strengths of the
 * same verdict rather than two verdicts — the only pairing the document draws
 * no line through.
 */

export type VerdictTone = "strong" | "ok" | "transfer" | "gap" | "blocked" | "neutral";

export interface VerdictColumn {
  key: string;
  label: string;
  /** Every status that lands in this lane. */
  statuses: MatchStatus[];
  tone: VerdictTone;
  /** Whether this lane is a finding about the posting rather than about you. */
  unanswered?: boolean;
}

// A lane is headed by the label of the status in it, so the field does not
// introduce a second vocabulary for verdicts the rest of the product already
// names. "Covered" is the one exception and has to be: it holds two statuses,
// and heading it with either one would misname the other.
export const VERDICT_COLUMNS: VerdictColumn[] = [
  { key: "covered", label: "Covered", statuses: ["STRONG_MATCH", "MATCH"], tone: "strong" },
  {
    key: "partial",
    label: MATCH_STATUS_LABELS.PARTIAL_MATCH,
    statuses: ["PARTIAL_MATCH"],
    tone: "ok",
  },
  {
    key: "transfers",
    label: MATCH_STATUS_LABELS.TRANSFERABLE_MATCH,
    statuses: ["TRANSFERABLE_MATCH"],
    tone: "transfer",
  },
  { key: "gap", label: MATCH_STATUS_LABELS.GAP, statuses: ["GAP"], tone: "gap" },
  { key: "blocker", label: MATCH_STATUS_LABELS.BLOCKER, statuses: ["BLOCKER"], tone: "blocked" },
  {
    key: "nothing",
    label: MATCH_STATUS_LABELS.NO_EVIDENCE,
    statuses: ["NO_EVIDENCE"],
    tone: "neutral",
    unanswered: true,
  },
  {
    key: "unknown",
    label: MATCH_STATUS_LABELS.UNKNOWN,
    statuses: ["UNKNOWN"],
    tone: "neutral",
    unanswered: true,
  },
];

/** Which lane a status falls in. Total over `MatchStatus` by construction. */
export const COLUMN_FOR_STATUS: Record<MatchStatus, VerdictColumn> = Object.fromEntries(
  VERDICT_COLUMNS.flatMap((column) => column.statuses.map((status) => [status, column])),
) as Record<MatchStatus, VerdictColumn>;

export interface ImportanceBand {
  key: RequirementImportance;
  label: string;
  /** Whether a shortfall in this band counts against the figure. */
  counts: boolean;
  note: string;
}

/**
 * Insistence, strongest first.
 *
 * `counts` is not decoration: `docs/05-ai-and-matching.md` weights CORE and
 * REQUIRED and reads the rest as extras, so a gap three bands down does not
 * move the number. Saying which bands the figure answers to is the difference
 * between a user reading the field as a scorecard and reading it as what it
 * is.
 */
export const IMPORTANCE_BANDS: ImportanceBand[] = [
  {
    key: "CORE",
    label: IMPORTANCE_LABELS.CORE,
    counts: true,
    note: "A shortfall here caps the figure.",
  },
  {
    key: "REQUIRED",
    label: IMPORTANCE_LABELS.REQUIRED,
    counts: true,
    note: "Counted at full weight.",
  },
  {
    key: "PREFERRED",
    label: IMPORTANCE_LABELS.PREFERRED,
    counts: false,
    note: "Read as an extra. A gap here does not lower the figure.",
  },
  {
    key: "OPTIONAL",
    label: IMPORTANCE_LABELS.OPTIONAL,
    counts: false,
    note: "Read as an extra.",
  },
  {
    key: "UNKNOWN",
    label: IMPORTANCE_LABELS.UNKNOWN,
    counts: false,
    // Not the same as unimportant. The posting listed it without saying how
    // much it mattered, and reading that silence as "optional" would be us
    // deciding something the posting did not.
    note: "The posting did not say how much this matters.",
  },
];

export const VERDICT_ICONS: Record<VerdictTone, typeof CheckCircle2> = {
  strong: CheckCircle2,
  ok: CircleDashed,
  transfer: ArrowLeftRight,
  gap: MinusCircle,
  blocked: AlertOctagon,
  neutral: CircleHelp,
};

// Tokens, not palette entries — DEV-057. `globals.css` carries both themes.
export const VERDICT_TEXT: Record<VerdictTone, string> = {
  strong: "text-verdict-strong",
  ok: "text-verdict-partial",
  transfer: "text-verdict-transfer",
  gap: "text-verdict-gap",
  blocked: "text-verdict-blocked",
  neutral: "text-muted-foreground",
};

/**
 * The importance an item was scored under.
 *
 * `UNKNOWN` when the requirement did not travel with the item, which the API
 * only does for a payload built without the join. Falling back to the band the
 * posting was silent about is the honest place to put something whose
 * insistence we cannot read — it is not a claim that the posting said nothing,
 * and the band's own note says as much.
 */
export function importanceOf(item: MatchItem): RequirementImportance {
  return item.requirement?.importance ?? "UNKNOWN";
}

/**
 * What to call a requirement in one line.
 *
 * The resolved skill first, then our normalisation, then the explanation as a
 * last resort. Never `source_text`: that is the posting's sentence, it belongs
 * in the quote, and truncating it into a chip would put edited words in the
 * one place that must not be edited.
 */
export function shortName(item: MatchItem): string {
  const requirement = item.requirement;
  return requirement?.skill_name || requirement?.normalized_text || item.explanation;
}

/** How many items fall in each lane, including the lanes with none. */
export function countByColumn(items: MatchItem[]): Record<string, number> {
  const counts: Record<string, number> = Object.fromEntries(
    VERDICT_COLUMNS.map((column) => [column.key, 0]),
  );
  for (const item of items) {
    const column = COLUMN_FOR_STATUS[item.status];
    if (column) counts[column.key] = (counts[column.key] ?? 0) + 1;
  }
  return counts;
}
