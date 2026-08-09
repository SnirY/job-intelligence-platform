"use client";

import {
  RESUME_FAMILY_LABELS,
  SECTION_KIND_LABELS,
  VERSION_STATUS_LABELS,
  type Resume,
  type ResumeSectionKind,
  type ResumeVersionDetail,
  type ResumeVersionStatus,
} from "@jip/shared-types";
import { FileText, Loader2, Lock, Plus, Printer } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateResume,
  useCreateVersion,
  useRenderVersion,
  useResumes,
  useSaveContent,
  useSetVersionStatus,
  useVersion,
  useVersions,
} from "@/features/resumes/api";

const SECTION_ORDER: ResumeSectionKind[] = [
  "SUMMARY",
  "SKILLS",
  "EXPERIENCE",
  "PROJECTS",
  "EDUCATION",
  "CERTIFICATIONS",
];

/**
 * Build a resume by hand, and version it.
 *
 * `docs/06-resume-engine.md` treats a resume as a *selected representation* of
 * the career profile, so this edits presentation only — nothing typed here
 * changes what the profile knows.
 *
 * The rule the screen is built around: a version that has been sent cannot be
 * edited. Rather than letting someone type into a frozen document and fail on
 * save, the editor reads `is_editable` from the server and offers a new version
 * instead.
 */
export function ResumeWorkspace() {
  const resumes = useResumes();
  const [selectedResume, setSelectedResume] = useState<string | null>(null);

  const current = selectedResume ?? resumes.data?.[0]?.id ?? null;

  if (resumes.isPending) return <Panel>Loading your resumes…</Panel>;
  if (resumes.isError) return <Panel tone="error">Could not load your resumes.</Panel>;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Resumes</h1>
          <p className="text-muted-foreground">
            A resume is a selection from your career profile, not a second copy of it.
          </p>
        </div>
      </header>

      {resumes.data.length === 0 ? (
        <CreateResume first />
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="resume-picker">Resume</Label>
              <Select
                id="resume-picker"
                className="w-64"
                value={current ?? ""}
                onChange={(event) => setSelectedResume(event.target.value)}
              >
                {resumes.data.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.title} · {RESUME_FAMILY_LABELS[resume.family]}
                  </option>
                ))}
              </Select>
            </div>
            <CreateResume />
          </div>

          {current && <ResumeEditor resume={resumes.data.find((r) => r.id === current)!} />}
        </>
      )}
    </div>
  );
}

function CreateResume({ first }: { first?: boolean }) {
  const create = useCreateResume();
  const [title, setTitle] = useState("");

  const submit = () => {
    if (!title.trim()) return;
    create.mutate({ title: title.trim(), family: "BASE" }, { onSuccess: () => setTitle("") });
  };

  if (first) {
    return (
      <Card>
        <CardContent className="space-y-3 p-8 text-center">
          <p className="text-sm font-medium">Start with a base resume.</p>
          <p className="text-sm text-muted-foreground">
            One general version you keep current. Tailored versions for specific jobs are made from
            it, so you never start from a blank page.
          </p>
          <div className="mx-auto flex max-w-sm items-end gap-2">
            <div className="flex-1 space-y-2 text-left">
              <Label htmlFor="new-resume">Name</Label>
              <Input
                id="new-resume"
                placeholder="Backend Engineer"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <Button type="button" disabled={!title.trim() || create.isPending} onClick={submit}>
              <Plus aria-hidden className="size-4" />
              Create
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex items-end gap-2">
      <div className="space-y-2">
        <Label htmlFor="new-resume-inline">New resume</Label>
        <Input
          id="new-resume-inline"
          className="w-56"
          placeholder="AI / Computer Vision"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <Button
        type="button"
        variant="secondary"
        disabled={!title.trim() || create.isPending}
        onClick={submit}
      >
        <Plus aria-hidden className="size-4" />
        Add
      </Button>
    </div>
  );
}

function ResumeEditor({ resume }: { resume: Resume }) {
  const versions = useVersions(resume.id);
  const [selected, setSelected] = useState<string | null>(null);
  const createVersion = useCreateVersion(resume.id);

  const currentId = selected ?? versions.data?.[0]?.id ?? null;
  const version = useVersion(currentId);

  if (versions.isPending) return <Panel>Loading versions…</Panel>;
  if (versions.isError || !versions.data) {
    return <Panel tone="error">Could not load the versions of this resume.</Panel>;
  }

  if (versions.data.length === 0) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm font-medium">This resume has no versions yet.</p>
          <Button
            type="button"
            disabled={createVersion.isPending}
            onClick={() => createVersion.mutate({ label: "First draft" })}
          >
            <Plus aria-hidden className="size-4" />
            Create the first version
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Versions:</span>
        {versions.data.map((row) => (
          <button
            key={row.id}
            type="button"
            aria-current={row.id === currentId}
            className={
              row.id === currentId
                ? "rounded border px-2 py-1 text-xs font-medium"
                : "rounded border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
            }
            onClick={() => setSelected(row.id)}
          >
            v{row.version} · {VERSION_STATUS_LABELS[row.status]}
          </button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={createVersion.isPending}
          onClick={() =>
            createVersion.mutate({ label: "New draft", copy_from: currentId ?? undefined })
          }
        >
          <Plus aria-hidden className="size-4" />
          New version from this
        </Button>
      </div>

      {version.isPending && <Panel>Loading…</Panel>}
      {version.data && <VersionEditor version={version.data} />}
    </div>
  );
}

function VersionEditor({ version }: { version: ResumeVersionDetail }) {
  const save = useSaveContent(version.id);
  const setStatus = useSetVersionStatus(version.id);
  const [draft, setDraft] = useState(() => toDraft(version));

  // The chosen version changes underneath this component, so the local draft
  // has to follow it. Keyed on id rather than on the object: re-syncing on
  // every refetch would discard whatever the user had typed.
  useEffect(() => setDraft(toDraft(version)), [version.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const frozen = !version.is_editable;

  // Recomputed on every keystroke, which is the point: the save is refused
  // while a heading has nothing under it, and the refusal has to clear the
  // moment the user fixes it. DEV-044.
  const dangling = danglingHeadings(draft);

  return (
    <div className="space-y-4">
      {frozen && (
        <div className="flex items-start gap-2 rounded-md border p-3 text-sm">
          <Lock aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <p>
            This version has been {version.status === "USED" ? "sent" : "archived"}, so its content
            is fixed. An application record has to describe the document that was actually sent.
            Create a new version to keep working.
          </p>
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">
              Version {version.version}
              {version.label ? ` — ${version.label}` : ""}
            </CardTitle>
            <CardDescription>What appears on the page.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={frozen ? "outline" : "default"}>
              {VERSION_STATUS_LABELS[version.status]}
            </Badge>
            <PrintButton versionId={version.id} />
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {SECTION_ORDER.map((kind) => (
            <div key={kind} className="space-y-2">
              <Label htmlFor={`section-${kind}`}>{SECTION_KIND_LABELS[kind]}</Label>
              <Textarea
                id={`section-${kind}`}
                className="min-h-24 font-mono text-xs"
                placeholder="One line per bullet. Prefix a line with # to make it a heading."
                disabled={frozen}
                value={draft[kind] ?? ""}
                onChange={(event) => setDraft({ ...draft, [kind]: event.target.value })}
              />
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              disabled={frozen || save.isPending || dangling.length > 0}
              onClick={() => save.mutate(fromDraft(draft))}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>

            <StatusActions
              status={version.status}
              pending={setStatus.isPending}
              onSet={(next) => setStatus.mutate(next)}
            />

            <p aria-live="polite" className="text-sm">
              {save.isSuccess && !save.isPending && dangling.length === 0 && (
                <span className="text-muted-foreground">Saved.</span>
              )}
              {save.isError && <span className="text-destructive">Could not save.</span>}
            </p>
          </div>

          {dangling.length > 0 && (
            /* DEV-044. Refused before the request rather than reported after
               it: the save would succeed, and the line would be gone under a
               "Saved." that had nothing to do with it. */
            <div
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
            >
              <p className="font-medium">
                {dangling.length === 1
                  ? "One heading has no lines under it."
                  : `${dangling.length} headings have no lines under them.`}
              </p>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                {dangling.map((entry) => (
                  <li key={`${entry.kind}-${entry.heading}`}>
                    <span className="font-medium">{SECTION_KIND_LABELS[entry.kind]}</span>
                    {" — "}
                    {entry.heading || "(empty heading)"}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-muted-foreground">
                A heading belongs to the bullets beneath it, so one on its own has nowhere to be
                stored. Add a line under it, or remove the <code>#</code> to make it a bullet.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Open the printable version in a new tab.
 *
 * The tab is opened synchronously on the click and filled in once the HTML
 * arrives; opening it after the `await` is what browsers block as a popup.
 * ADR-0006: the browser's own print dialog is the PDF exporter.
 */
function PrintButton({ versionId }: { versionId: string }) {
  const render = useRenderVersion();

  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={render.isPending}
        onClick={() => {
          // No `noopener` here, unusually: it severs the handle and returns
          // null, and we need the handle to write into. Safe because the tab
          // starts at about:blank and the only thing that ever reaches it is
          // our own rendered document.
          const tab = window.open("", "_blank");
          render.mutate(versionId, {
            onSuccess: (html) => {
              if (!tab) return;
              tab.document.write(html);
              tab.document.close();
            },
            onError: () => tab?.close(),
          });
        }}
      >
        <Printer aria-hidden className="size-4" />
        {render.isPending ? "Preparing…" : "Preview / print"}
      </Button>
      {render.isError && <span className="text-xs text-destructive">Could not render.</span>}
    </div>
  );
}

function StatusActions({
  status,
  pending,
  onSet,
}: {
  status: ResumeVersionStatus;
  pending: boolean;
  onSet: (status: ResumeVersionStatus) => void;
}) {
  // Only transitions the server allows. Offering a button that returns 409
  // would be telling the user something is possible when it is not.
  const next: ResumeVersionStatus[] =
    status === "DRAFT"
      ? ["REVIEW", "APPROVED"]
      : status === "REVIEW"
        ? ["APPROVED"]
        : status === "APPROVED"
          ? ["USED"]
          : [];

  return (
    <>
      {next.map((target) => (
        <Button
          key={target}
          type="button"
          variant="secondary"
          disabled={pending}
          onClick={() => onSet(target)}
        >
          {target === "USED" ? "Mark as sent" : `Move to ${VERSION_STATUS_LABELS[target]}`}
        </Button>
      ))}
    </>
  );
}

/**
 * The editor works in plain text, one line per item.
 *
 * A structured drag-and-drop editor is the eventual answer, but a textarea is
 * the honest MVP: it is fast to type into, it round-trips without loss, and it
 * does not pretend to a fidelity the renderer cannot yet deliver. A line
 * starting with `#` is a heading, which is how a role's title attaches to its
 * bullets.
 */
function toDraft(version: ResumeVersionDetail): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const section of version.sections) {
    draft[section.kind] = section.items
      .map((item) => (item.heading ? `# ${item.heading}\n${item.text}` : item.text))
      .join("\n");
  }
  return draft;
}

/** A heading the data model has nowhere to put. See `danglingHeadings`. */
export interface DanglingHeading {
  kind: ResumeSectionKind;
  heading: string;
}

/**
 * Headings with no bullet beneath them, which a save would silently discard.
 *
 * DEV-044. `fromDraft` carries a heading in a local until a bullet arrives to
 * attach it to, because `ResumeItem` has no standalone-heading form. A `#` line
 * with nothing ordinary after it therefore reached the end of the loop and was
 * dropped — and the screen said "Saved." A section of only headings vanished
 * whole.
 *
 * That explains the behaviour and does not excuse it. This is not a failure
 * path losing work; it is the success path doing it, under an explicit
 * confirmation that nothing was lost. So the save is refused and the line is
 * named, which is honest and costs no schema change.
 */
export function danglingHeadings(draft: Record<string, string>): DanglingHeading[] {
  const dangling: DanglingHeading[] = [];

  for (const kind of SECTION_ORDER) {
    let pending: string | null = null;

    for (const raw of (draft[kind] ?? "").split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith("#")) {
        // Two headings in a row lose the first one for the same reason, so each
        // is reported rather than only the last.
        if (pending !== null) dangling.push({ kind, heading: pending });
        pending = line.replace(/^#+\s*/, "");
        continue;
      }
      pending = null;
    }

    if (pending !== null) dangling.push({ kind, heading: pending });
  }

  return dangling;
}

function fromDraft(draft: Record<string, string>) {
  const sections = SECTION_ORDER.filter((kind) => (draft[kind] ?? "").trim()).map((kind, order) => {
    const items: { text: string; heading: string | null; display_order: number }[] = [];
    let heading: string | null = null;

    for (const raw of (draft[kind] ?? "").split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith("#")) {
        heading = line.replace(/^#+\s*/, "") || null;
        continue;
      }
      items.push({ text: line, heading, display_order: items.length });
    }

    return { kind, display_order: order, items };
  });

  return { sections: sections.filter((section) => section.items.length > 0) };
}

function Panel({ children, tone }: { children: React.ReactNode; tone?: "error" }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-2 p-6">
        {tone !== "error" && <Loader2 aria-hidden className="size-4 animate-spin" />}
        {tone === "error" && <FileText aria-hidden className="size-4" />}
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
