import {
  CANDIDATE_FLAG_LABELS,
  type CandidateFlag,
  type CandidateType,
  type ExtractionItem,
} from "@jip/shared-types";

/**
 * Reading an extraction item's untyped payload.
 *
 * The shape differs per candidate type, so the payload arrives as
 * `Record<string, unknown>`. These accessors are the only place that shape is
 * assumed, which keeps the assumption in one file instead of scattered through
 * the components.
 */

/** What an approval would actually write: the edit if there is one. */
export function effectivePayload(item: ExtractionItem): Record<string, unknown> {
  return item.edited_payload ?? item.payload;
}

export function readString(item: ExtractionItem, key: string): string | null {
  const value = effectivePayload(item)[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export function readBoolean(item: ExtractionItem, key: string): boolean {
  return effectivePayload(item)[key] === true;
}

/** Validation flags, which the review screen turns into a visible warning. */
export function readFlags(item: ExtractionItem): CandidateFlag[] {
  const flags = item.payload.flags;
  if (!Array.isArray(flags)) return [];
  return flags.filter(
    (f): f is CandidateFlag => typeof f === "string" && f in CANDIDATE_FLAG_LABELS,
  );
}

/**
 * A one-line title for any candidate type.
 *
 * Falls back through the fields each type actually has, so a new type without
 * a dedicated branch still renders something meaningful rather than blank.
 */
export function candidateTitle(item: ExtractionItem): string {
  switch (item.candidate_type) {
    case "SKILL":
    case "PROJECT_SKILL":
    case "PROJECT":
      return readString(item, "name") ?? "Untitled";
    case "EXPERIENCE":
      return [readString(item, "title"), readString(item, "company")].filter(Boolean).join(" · ");
    case "EXPERIENCE_ACHIEVEMENT":
      return readString(item, "text") ?? "Untitled";
    case "EDUCATION":
      return (
        [readString(item, "degree"), readString(item, "field_of_study")]
          .filter(Boolean)
          .join(", ") ||
        (readString(item, "institution") ?? "Untitled")
      );
  }
}

/** Supporting detail shown under the title. */
export function candidateDetail(item: ExtractionItem): string | null {
  const dates = formatRange(
    readString(item, "start_date"),
    readString(item, "end_date"),
    readBoolean(item, "is_current"),
  );

  switch (item.candidate_type) {
    case "SKILL":
      return [readString(item, "category"), dates].filter(Boolean).join(" · ") || null;
    case "EXPERIENCE":
      return [readString(item, "location"), dates].filter(Boolean).join(" · ") || null;
    case "PROJECT":
      return [readString(item, "project_type"), dates].filter(Boolean).join(" · ") || null;
    case "EDUCATION":
      return [readString(item, "institution"), dates].filter(Boolean).join(" · ") || null;
    default:
      return null;
  }
}

/**
 * Fields the edit form offers, per candidate type.
 *
 * Deliberately not every field in the payload: `flags` and the date-precision
 * markers are validation output, not things a person edits.
 */
export function editableFields(candidateType: CandidateType): readonly string[] {
  switch (candidateType) {
    case "SKILL":
    case "PROJECT_SKILL":
      return ["name"];
    case "EXPERIENCE":
      return ["company", "title", "location", "start_date", "end_date", "description"];
    case "EXPERIENCE_ACHIEVEMENT":
      return ["text"];
    case "PROJECT":
      return ["name", "summary", "description", "start_date", "end_date", "repository_url"];
    case "EDUCATION":
      return ["institution", "degree", "field_of_study", "start_date", "end_date", "grade"];
  }
}

/**
 * How exact an extracted date is.
 *
 * A year-only date is stored as 1 January, which is indistinguishable from a
 * real 1 January unless the precision is shown alongside it.
 */
export function datePrecisionNote(item: ExtractionItem): string | null {
  const start = effectivePayload(item).start_date_precision;
  const end = effectivePayload(item).end_date_precision;
  const imprecise = [start, end].filter((p) => p === "YEAR" || p === "MONTH");
  if (imprecise.length === 0) return null;
  return imprecise.includes("YEAR")
    ? "Your document gave only a year, so the day and month are approximate."
    : "Your document gave only a month, so the day is approximate.";
}

/** Children of an item, in display order. */
export function childrenOf(items: ExtractionItem[], parentId: string): ExtractionItem[] {
  return items
    .filter((i) => i.parent_item_id === parentId)
    .sort((a, b) => a.display_order - b.display_order);
}

/** Top-level items of one type, in display order. */
export function topLevelOfType(items: ExtractionItem[], type: CandidateType): ExtractionItem[] {
  return items
    .filter((i) => i.candidate_type === type && i.parent_item_id === null)
    .sort((a, b) => a.display_order - b.display_order);
}

/** Whether the user has already decided on this item. */
export function isDecided(item: ExtractionItem): boolean {
  return item.decision !== "PENDING";
}

function formatRange(start: string | null, end: string | null, isCurrent: boolean): string | null {
  const year = (value: string | null) => (value ? value.slice(0, 7) : null);
  const from = year(start);
  const to = isCurrent ? "Present" : year(end);
  if (!from && !to) return null;
  if (from && to) return `${from} – ${to}`;
  return from ?? to;
}
