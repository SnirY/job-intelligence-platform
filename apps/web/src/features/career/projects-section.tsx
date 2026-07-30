"use client";

import {
  API_ROUTES,
  PROJECT_STATUS_LABELS,
  PROJECT_TYPE_LABELS,
  type Project,
  type ProjectCreate,
  type ProjectStatus,
  type ProjectType,
} from "@jip/shared-types";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { CollectionSection, formatDateRange } from "@/features/career/section";
import { useCollection, useDraft } from "@/features/career/use-collection";
import { ApiError } from "@/lib/api";

const EMPTY: ProjectCreate = {
  name: "",
  project_type: null,
  status: null,
  summary: "",
  description: "",
  start_date: "",
  end_date: "",
  repository_url: "",
  demo_url: "",
};

function toPayload(draft: ProjectCreate): ProjectCreate {
  return {
    name: draft.name.trim(),
    project_type: draft.project_type || null,
    status: draft.status || null,
    summary: draft.summary?.trim() || null,
    description: draft.description?.trim() || null,
    start_date: draft.start_date || null,
    end_date: draft.end_date || null,
    repository_url: draft.repository_url?.trim() || null,
    demo_url: draft.demo_url?.trim() || null,
  };
}

/** A stored project back into the shape the form edits. */
function toDraft(project: Project): ProjectCreate {
  return {
    name: project.name,
    project_type: project.project_type,
    status: project.status,
    summary: project.summary ?? "",
    description: project.description ?? "",
    start_date: project.start_date ?? "",
    end_date: project.end_date ?? "",
    repository_url: project.repository_url ?? "",
    demo_url: project.demo_url ?? "",
  };
}

export function ProjectsSection() {
  const { query, create, remove, update } = useCollection<Project, ProjectCreate>(
    ["career", "projects"],
    API_ROUTES.careerProjects,
  );
  const { draft, setDraft, editingId, isEditing, edit, reset } = useDraft(EMPTY);

  const nameIsBlank = draft.name.trim() === "";
  const saving = create.isPending || update.isPending;

  return (
    <CollectionSection
      title="Projects"
      description="What you have built. For many people this is stronger evidence than a job title."
      items={query.data}
      isPending={query.isPending}
      error={query.error}
      emptyMessage="No projects yet. Add what you have built, including personal work."
      renderItem={(project) => (
        <>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{project.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {[
                project.project_type ? PROJECT_TYPE_LABELS[project.project_type] : null,
                project.status ? PROJECT_STATUS_LABELS[project.status] : null,
                formatDateRange(project.start_date, project.end_date),
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {project.repository_url && (
              <a
                className="text-xs text-primary underline underline-offset-2"
                href={project.repository_url}
                target="_blank"
                // noreferrer as well as noopener: without it the destination
                // learns where the link came from.
                rel="noopener noreferrer"
              >
                Repository
              </a>
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Edit ${project.name}`}
            onClick={() => edit(project.id, toDraft(project))}
          >
            <Pencil aria-hidden className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${project.name}`}
            disabled={remove.isPending}
            onClick={() => remove.mutate(project.id)}
          >
            <Trash2 aria-hidden className="size-4" />
          </Button>
        </>
      )}
      form={
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (nameIsBlank) return;
            const body = toPayload(draft);
            if (editingId) {
              update.mutate({ id: editingId, body }, { onSuccess: reset });
            } else {
              create.mutate(body, { onSuccess: reset });
            }
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="proj-name">Name</Label>
              <Input
                id="proj-name"
                value={draft.name}
                maxLength={200}
                placeholder="Match engine prototype"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-type">Type</Label>
              <Select
                id="proj-type"
                value={draft.project_type ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    project_type: (event.target.value || null) as ProjectType | null,
                  })
                }
              >
                <option value="">Not specified</option>
                {Object.entries(PROJECT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-status">Status</Label>
              <Select
                id="proj-status"
                value={draft.status ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    status: (event.target.value || null) as ProjectStatus | null,
                  })
                }
              >
                <option value="">Not specified</option>
                {Object.entries(PROJECT_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-repo">Repository URL</Label>
              <Input
                id="proj-repo"
                type="url"
                value={draft.repository_url ?? ""}
                placeholder="https://github.com/you/project"
                onChange={(event) => setDraft({ ...draft, repository_url: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-start">Start date</Label>
              <Input
                id="proj-start"
                type="date"
                value={draft.start_date ?? ""}
                onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj-end">End date</Label>
              <Input
                id="proj-end"
                type="date"
                value={draft.end_date ?? ""}
                onChange={(event) => setDraft({ ...draft, end_date: event.target.value })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="proj-description">Description</Label>
            <Textarea
              id="proj-description"
              rows={3}
              maxLength={5000}
              value={draft.description ?? ""}
              placeholder="What it does, what you built, and what was hard about it."
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={nameIsBlank || saving}>
              {isEditing ? (
                <Pencil aria-hidden className="size-4" />
              ) : (
                <Plus aria-hidden className="size-4" />
              )}
              {saving ? "Saving…" : isEditing ? "Save changes" : "Add project"}
            </Button>
            {isEditing && (
              <Button type="button" variant="ghost" onClick={reset}>
                Cancel
              </Button>
            )}
            <p aria-live="polite" className="text-sm text-destructive">
              {create.isError &&
                (create.error instanceof ApiError && create.error.status === 409
                  ? "You already have a project with that name."
                  : "Could not add that project.")}
              {update.isError && "Could not save those changes."}
              {remove.isError && "Could not remove that project."}
            </p>
          </div>
        </form>
      }
    />
  );
}
