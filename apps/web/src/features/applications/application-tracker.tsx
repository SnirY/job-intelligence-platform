"use client";

import {
  APPLICATION_SOURCE_LABELS,
  APPLICATION_STATUS_LABELS,
  BOARD_COLUMNS,
  isTerminal,
  type Application,
  type ApplicationEvent,
  type ApplicationStatus,
} from "@jip/shared-types";
import { Clock, LayoutGrid, Table2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  useAddNote,
  useApplications,
  useChangeStatus,
  useEvents,
  useRecordFeedback,
} from "@/features/applications/api";
import { ApiError } from "@/lib/api";

/**
 * The application tracker.
 *
 * `docs/08-ui-ux.md` asks for a polished visual Kanban by default, with a table
 * as the second view. Both read the same list; neither can move a card by a
 * route that skips the history.
 *
 * Movement is a `<Select>` rather than drag-and-drop. Two reasons, and the
 * second is the real one: the server decides which moves are legal and returns
 * that list per card, so a control built from `allowed_transitions` cannot offer
 * an illegal move — where a drag target would, and would then have to animate
 * the card back. And a keyboard user gets the same tracker.
 */
export function ApplicationTracker() {
  const [view, setView] = useState<"board" | "table">("board");
  const [showArchived, setShowArchived] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const applications = useApplications(showArchived);

  if (applications.isPending) return <Panel>Loading your applications…</Panel>;
  if (applications.isError || !applications.data) {
    return <Panel tone="error">Could not load your applications.</Panel>;
  }

  const rows = applications.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Applications</h1>
          <p className="text-muted-foreground">
            Where each one stands, and the exact resume you sent with it.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={view === "board" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setView("board")}
          >
            <LayoutGrid aria-hidden className="size-4" />
            Board
          </Button>
          <Button
            type="button"
            variant={view === "table" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setView("table")}
          >
            <Table2 aria-hidden className="size-4" />
            Table
          </Button>
        </div>
      </header>

      {rows.length === 0 ? (
        <Card>
          <CardContent className="space-y-2 p-8 text-center">
            <p className="text-sm font-medium">Nothing tracked yet.</p>
            <p className="text-sm text-muted-foreground">
              Open a job and start tracking it. A job you are only considering does not need an
              application — this is for the ones you are actually pursuing.
            </p>
          </CardContent>
        </Card>
      ) : view === "board" ? (
        <Board rows={rows} onOpen={setSelected} />
      ) : (
        <TableView rows={rows} onOpen={setSelected} />
      )}

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(event) => setShowArchived(event.target.checked)}
        />
        Include archived
      </label>

      {selected && <Detail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

/**
 * The board.
 *
 * Only live columns. A Kanban with a Rejected column is a monument to
 * rejection, and an ended application is history rather than work in progress —
 * the table shows those.
 */
function Board({ rows, onOpen }: { rows: Application[]; onOpen: (id: string) => void }) {
  const ended = rows.filter((row) => isTerminal(row.status));

  return (
    <div className="space-y-4">
      <div className="flex gap-3 overflow-x-auto pb-2">
        {BOARD_COLUMNS.map((column) => {
          const cards = rows.filter((row) => row.status === column);
          return (
            <section key={column} className="w-64 shrink-0 space-y-2">
              <header className="flex items-center justify-between px-1">
                <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {APPLICATION_STATUS_LABELS[column]}
                </h2>
                <span className="text-xs text-muted-foreground">{cards.length}</span>
              </header>

              <div className="space-y-2">
                {cards.map((row) => (
                  <ApplicationCard key={row.id} application={row} onOpen={onOpen} />
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {ended.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {ended.length} finished {ended.length === 1 ? "application is" : "applications are"} not
          on the board. The table view shows them.
        </p>
      )}
    </div>
  );
}

function ApplicationCard({
  application,
  onOpen,
}: {
  application: Application;
  onOpen: (id: string) => void;
}) {
  return (
    <article className="space-y-2 rounded-md border bg-card p-3">
      <button
        type="button"
        className="block w-full text-left"
        onClick={() => onOpen(application.id)}
      >
        <p className="truncate text-sm font-medium">{application.job_title}</p>
        {application.company && (
          <p className="truncate text-xs text-muted-foreground">{application.company}</p>
        )}
      </button>

      <StageAge days={application.days_in_stage} />
      <StatusPicker application={application} />
    </article>
  );
}

/**
 * How long this has sat where it is.
 *
 * `docs/08-ui-ux.md` asks for "subtle stage-aging indicators". Subtle is the
 * operative word: a card going red after a week would make a normal hiring
 * process look like a series of emergencies, so this only speaks up once a
 * delay is genuinely unusual, and even then it describes rather than alarms.
 */
function StageAge({ days }: { days: number | null }) {
  if (days === null) return null;

  const tone =
    days >= 21
      ? "text-destructive"
      : days >= 10
        ? "text-muted-foreground"
        : "text-muted-foreground";

  return (
    <p className={`text-xs ${tone}`}>
      {days === 0 ? "Moved today" : days === 1 ? "1 day here" : `${days} days here`}
      {days >= 21 && " — worth a follow-up"}
    </p>
  );
}

/**
 * The move control.
 *
 * Built entirely from `allowed_transitions`, which the server computes from the
 * lifecycle table. Nothing here knows the rules, which is why it cannot
 * contradict them.
 */
function StatusPicker({ application }: { application: Application }) {
  const change = useChangeStatus();

  if (application.allowed_transitions.length === 0) {
    return <p className="text-xs text-muted-foreground">No further changes.</p>;
  }

  return (
    <div className="space-y-1">
      <Select
        aria-label={`Move ${application.job_title}`}
        className="h-8 w-full text-xs"
        value=""
        disabled={change.isPending}
        onChange={(event) => {
          const next = event.target.value as ApplicationStatus;
          if (next) change.mutate({ id: application.id, status: next });
        }}
      >
        <option value="">Move to…</option>
        {application.allowed_transitions.map((status) => (
          <option key={status} value={status}>
            {APPLICATION_STATUS_LABELS[status]}
          </option>
        ))}
      </Select>

      {change.isError && (
        <p className="text-xs text-destructive">
          {change.error instanceof ApiError
            ? change.error.message
            : "That move could not be saved."}
        </p>
      )}
    </div>
  );
}

function TableView({ rows, onOpen }: { rows: Application[]; onOpen: (id: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/40 text-left">
          <tr>
            <th className="p-3 font-medium">Role</th>
            <th className="p-3 font-medium">Company</th>
            <th className="p-3 font-medium">Status</th>
            <th className="p-3 font-medium">Applied</th>
            <th className="p-3 font-medium">In stage</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b last:border-0">
              <td className="p-3">
                <button
                  type="button"
                  className="text-left underline-offset-4 hover:underline"
                  onClick={() => onOpen(row.id)}
                >
                  {row.job_title}
                </button>
              </td>
              <td className="p-3 text-muted-foreground">{row.company ?? "—"}</td>
              <td className="p-3">
                <Badge variant={isTerminal(row.status) ? "outline" : "default"}>
                  {APPLICATION_STATUS_LABELS[row.status]}
                </Badge>
              </td>
              <td className="p-3 text-muted-foreground">{formatDate(row.applied_at)}</td>
              <td className="p-3 text-muted-foreground">
                {row.days_in_stage === null ? "—" : `${row.days_in_stage}d`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The timeline, and the two things only the user can tell us. */
function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const events = useEvents(id);
  const applications = useApplications(true);
  const note = useAddNote(id);
  const feedback = useRecordFeedback(id);
  const [noteText, setNoteText] = useState("");
  const [feedbackText, setFeedbackText] = useState("");

  const application = applications.data?.find((row) => row.id === id);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">{application?.job_title ?? "Application"}</CardTitle>
          <CardDescription>
            {application?.company ?? "—"}
            {application?.source && ` · ${APPLICATION_SOURCE_LABELS[application.source]}`}
          </CardDescription>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </CardHeader>

      <CardContent className="space-y-6">
        <section className="space-y-2">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Clock aria-hidden className="size-4 text-muted-foreground" />
            Timeline
          </h3>
          {events.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
          {events.data && <Timeline events={events.data} />}
        </section>

        {application?.rejection_feedback && (
          <section className="space-y-1">
            <h3 className="text-sm font-medium">What they told you</h3>
            {/* Their words, kept apart from anything the system concluded.
                docs/07 forbids presenting a guessed reason as fact. */}
            <p className="whitespace-pre-wrap rounded-md border p-3 text-sm">
              {application.rejection_feedback}
            </p>
          </section>
        )}

        <section className="space-y-2">
          <h3 className="text-sm font-medium">Add a note</h3>
          <Textarea
            aria-label="Note"
            className="min-h-20 text-sm"
            placeholder="Recruiter said they would come back next week."
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
          />
          <Button
            type="button"
            size="sm"
            disabled={!noteText.trim() || note.isPending}
            onClick={() => note.mutate(noteText.trim(), { onSuccess: () => setNoteText("") })}
          >
            {note.isPending ? "Saving…" : "Add to timeline"}
          </Button>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-medium">Feedback from the employer</h3>
          <p className="text-xs text-muted-foreground">
            Only what they actually said. We never guess a reason and never present one as fact.
          </p>
          <Textarea
            aria-label="Employer feedback"
            className="min-h-20 text-sm"
            value={feedbackText}
            onChange={(event) => setFeedbackText(event.target.value)}
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!feedbackText.trim() || feedback.isPending}
            onClick={() =>
              feedback.mutate(feedbackText.trim(), { onSuccess: () => setFeedbackText("") })
            }
          >
            {feedback.isPending ? "Saving…" : "Record feedback"}
          </Button>
        </section>
      </CardContent>
    </Card>
  );
}

function Timeline({ events }: { events: ApplicationEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>;
  }

  return (
    <ol className="space-y-3 border-l pl-4">
      {events.map((event) => (
        <li key={event.id} className="space-y-0.5">
          <p className="text-sm">{event.summary}</p>
          <p className="text-xs text-muted-foreground">{formatDate(event.occurred_at)}</p>
          {event.detail && (
            <p className="whitespace-pre-wrap text-xs text-muted-foreground">{event.detail}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString();
}

function Panel({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <Card>
      <CardContent className="p-6">
        <p
          className={
            tone === "error" ? "text-sm text-destructive" : "text-sm text-muted-foreground"
          }
        >
          {children}
        </p>
      </CardContent>
    </Card>
  );
}
