"use client";

import { MATCH_STATUS_LABELS, type MatchItem } from "@jip/shared-types";

import { Badge } from "@/components/ui/badge";
import {
  COLUMN_FOR_STATUS,
  IMPORTANCE_BANDS,
  VERDICT_COLUMNS,
  VERDICT_ICONS,
  VERDICT_TEXT,
  countByColumn,
  importanceOf,
  shortName,
  type VerdictColumn,
} from "@/features/jobs/match-axes";

/**
 * Every requirement at once, placed on two axes.
 *
 * The screen used to say the same thing four times — a blockers card, a
 * strengths card, a gaps card, a transferable card, and then the whole list
 * again underneath. Five lists of one set. None of them showed how the set was
 * shaped, and the two facts that decide whether a job is worth applying to —
 * where the shortfalls are, and whether they sit in a band that counts — were
 * only recoverable by reading all five and holding them in your head.
 *
 * Here position does that work. A chip high and left is a requirement the
 * posting leaned on and the profile answers; low and right is one nobody needs
 * to worry about. An empty Blocker column is visible as emptiness.
 *
 * A field is not a substitute for a list, so it is not offered as one. The
 * toggle switches to the posting's own order, which is the textual alternative
 * `docs/08-ui-ux.md` asks every chart for, and it is a real reading rather than
 * a concession: the order a posting wrote its requirements in is information
 * this arrangement deliberately throws away.
 */
export function RequirementField({
  items,
  selectedId,
  onSelect,
  view,
  onView,
}: {
  items: MatchItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  view: "field" | "order";
  onView: (view: "field" | "order") => void;
}) {
  const counts = countByColumn(items);

  return (
    <section
      aria-labelledby="requirement-field-heading"
      className="flex min-h-0 flex-col rounded-xl border bg-card"
    >
      <header className="flex flex-wrap items-end justify-between gap-3 px-5 pb-3.5 pt-5">
        <div>
          <h3 id="requirement-field-heading" className="text-lg font-semibold">
            Requirement by requirement
          </h3>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Down: how much the posting insists. Across: what your profile answered.
          </p>
        </div>
        <ViewToggle view={view} onView={onView} />
      </header>

      {view === "field" ? (
        <Field items={items} counts={counts} selectedId={selectedId} onSelect={onSelect} />
      ) : (
        <PostingOrder items={items} selectedId={selectedId} onSelect={onSelect} />
      )}
    </section>
  );
}

function ViewToggle({
  view,
  onView,
}: {
  view: "field" | "order";
  onView: (view: "field" | "order") => void;
}) {
  return (
    <div
      role="group"
      aria-label="How to arrange the requirements"
      className="flex gap-1 rounded-lg border p-0.5"
    >
      {(
        [
          ["field", "Field"],
          ["order", "Posting order"],
        ] as const
      ).map(([key, label]) => (
        <button
          key={key}
          type="button"
          aria-pressed={view === key}
          onClick={() => onView(key)}
          className={
            view === key
              ? "h-7 rounded-md bg-secondary px-3 text-sm font-medium"
              : "h-7 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted"
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The grid template, shared by the header row and every band so they align. */
const FIELD_GRID = "grid grid-cols-[104px_repeat(7,minmax(0,1fr))] gap-2";

function Field({
  items,
  counts,
  selectedId,
  onSelect,
}: {
  items: MatchItem[];
  counts: Record<string, number>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      <div className={`${FIELD_GRID} border-b px-5 pb-2.5`}>
        <span />
        {VERDICT_COLUMNS.map((column) => {
          const Icon = VERDICT_ICONS[column.tone];
          return (
            <div key={column.key} className="flex min-w-0 flex-col gap-1">
              <Icon aria-hidden className={`size-3.5 ${VERDICT_TEXT[column.tone]}`} />
              <span className="text-xs font-medium leading-tight">{column.label}</span>
              <span className="font-mono text-xs text-muted-foreground">
                {counts[column.key] ?? 0}
              </span>
            </div>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5">
        {IMPORTANCE_BANDS.map((band) => {
          const inBand = items.filter((item) => importanceOf(item) === band.key);
          return (
            <div key={band.key} className={`${FIELD_GRID} border-b py-3.5`}>
              <div className="pt-0.5">
                <p className="text-sm font-semibold leading-tight">{band.label}</p>
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">{inBand.length}</p>
                <p className="mt-1.5 text-xs leading-snug text-foreground-faint">{band.note}</p>
              </div>

              {VERDICT_COLUMNS.map((column) => (
                <div key={column.key} className="flex min-w-0 flex-col gap-1.5">
                  {inBand
                    .filter((item) => COLUMN_FOR_STATUS[item.status] === column)
                    .map((item) => (
                      <Chip
                        key={item.id}
                        item={item}
                        column={column}
                        band={band.label}
                        selected={item.id === selectedId}
                        onSelect={onSelect}
                      />
                    ))}
                </div>
              ))}
            </div>
          );
        })}

        <p className="my-3.5 text-xs leading-relaxed text-foreground-faint">
          Essential and required are the two bands a shortfall counts against. Preferred, optional
          and unstated do not lower the figure. They are read as extras, exactly as the posting
          worded them.
        </p>
      </div>
    </>
  );
}

function Chip({
  item,
  column,
  band,
  selected,
  onSelect,
}: {
  item: MatchItem;
  column: VerdictColumn;
  band: string;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const Icon = VERDICT_ICONS[column.tone];

  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      aria-pressed={selected}
      /* The accessible name says the two things the chip's position says, in
         the order the axes are read. Someone who cannot see where it sits is
         told what sitting there means, which is the only way a form that
         carries meaning in position carries it to everyone. */
      aria-label={`${shortName(item)} — ${band}, ${MATCH_STATUS_LABELS[item.status]}`}
      className={
        selected
          ? "flex items-start gap-1.5 rounded-lg border border-primary bg-secondary px-2 py-1.5 text-left text-sm font-medium ring-1 ring-primary"
          : "flex items-start gap-1.5 rounded-lg border px-2 py-1.5 text-left text-sm font-medium hover:bg-muted"
      }
    >
      <Icon aria-hidden className={`mt-0.5 size-3.5 shrink-0 ${VERDICT_TEXT[column.tone]}`} />
      <span className="min-w-0 break-words">{shortName(item)}</span>
    </button>
  );
}

/**
 * The same requirements in the order the posting wrote them.
 *
 * Not a fallback. Sequence is information the field discards, and a posting
 * that opens with three essentials reads differently from one that buries them
 * on the second page.
 */
function PostingOrder({
  items,
  selectedId,
  onSelect,
}: {
  items: MatchItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const ordered = [...items].sort((a, b) => a.source_order - b.source_order);

  return (
    <ul className="min-h-0 flex-1 space-y-1.5 overflow-auto px-5 py-3.5">
      {ordered.map((item) => {
        const column = COLUMN_FOR_STATUS[item.status];
        const Icon = VERDICT_ICONS[column.tone];
        const band = IMPORTANCE_BANDS.find((row) => row.key === importanceOf(item));
        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.id)}
              aria-pressed={item.id === selectedId}
              className={
                item.id === selectedId
                  ? "flex w-full items-start gap-2.5 rounded-lg border border-primary bg-secondary px-3 py-2 text-left ring-1 ring-primary"
                  : "flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left hover:bg-muted"
              }
            >
              <Icon aria-hidden className={`mt-1 size-4 shrink-0 ${VERDICT_TEXT[column.tone]}`} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{shortName(item)}</span>
                <span className="block text-xs text-muted-foreground">{item.explanation}</span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <Badge variant="outline">{MATCH_STATUS_LABELS[item.status]}</Badge>
                {band && <span className="text-xs text-muted-foreground">{band.label}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
