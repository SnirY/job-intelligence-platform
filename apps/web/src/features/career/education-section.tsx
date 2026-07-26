"use client";

import { API_ROUTES, type Education, type EducationCreate } from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { CollectionSection, formatDateRange } from "@/features/career/section";
import { useCollection } from "@/features/career/use-collection";

const EMPTY: EducationCreate = {
  institution: "",
  degree: "",
  field_of_study: "",
  start_date: "",
  end_date: "",
  is_current: false,
  grade: "",
};

function toPayload(draft: EducationCreate): EducationCreate {
  return {
    institution: draft.institution.trim(),
    degree: draft.degree?.trim() || null,
    field_of_study: draft.field_of_study?.trim() || null,
    start_date: draft.start_date || null,
    end_date: draft.is_current ? null : draft.end_date || null,
    is_current: draft.is_current,
    grade: draft.grade?.trim() || null,
  };
}

export function EducationSection() {
  const { query, create, remove } = useCollection<Education, EducationCreate>(
    ["career", "education"],
    API_ROUTES.careerEducation,
  );
  const [draft, setDraft] = useState<EducationCreate>(EMPTY);

  const institutionIsBlank = draft.institution.trim() === "";

  return (
    <CollectionSection
      title="Education"
      description="Degrees, courses, and formal training."
      items={query.data}
      isPending={query.isPending}
      error={query.error}
      emptyMessage="No education yet. Add any formal study, including courses in progress."
      renderItem={(record) => (
        <>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {[record.degree, record.field_of_study].filter(Boolean).join(", ") ||
                record.institution}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {[
                record.degree || record.field_of_study ? record.institution : null,
                formatDateRange(record.start_date, record.end_date, record.is_current),
                record.grade,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${record.institution}`}
            disabled={remove.isPending}
            onClick={() => remove.mutate(record.id)}
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
            if (institutionIsBlank) return;
            create.mutate(toPayload(draft), { onSuccess: () => setDraft(EMPTY) });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="edu-institution">Institution</Label>
              <Input
                id="edu-institution"
                value={draft.institution}
                maxLength={200}
                placeholder="Technion"
                onChange={(event) => setDraft({ ...draft, institution: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edu-degree">Degree</Label>
              <Input
                id="edu-degree"
                value={draft.degree ?? ""}
                maxLength={200}
                placeholder="BSc"
                onChange={(event) => setDraft({ ...draft, degree: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edu-field">Field of study</Label>
              <Input
                id="edu-field"
                value={draft.field_of_study ?? ""}
                maxLength={200}
                placeholder="Computer Science"
                onChange={(event) => setDraft({ ...draft, field_of_study: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edu-grade">Grade</Label>
              <Input
                id="edu-grade"
                value={draft.grade ?? ""}
                maxLength={50}
                placeholder="88"
                onChange={(event) => setDraft({ ...draft, grade: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edu-start">Start date</Label>
              <Input
                id="edu-start"
                type="date"
                value={draft.start_date ?? ""}
                onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edu-end">End date</Label>
              <Input
                id="edu-end"
                type="date"
                value={draft.end_date ?? ""}
                disabled={draft.is_current}
                onChange={(event) => setDraft({ ...draft, end_date: event.target.value })}
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={draft.is_current}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      is_current: event.target.checked,
                      end_date: event.target.checked ? "" : draft.end_date,
                    })
                  }
                />
                Currently studying
              </label>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={institutionIsBlank || create.isPending}>
              <Plus aria-hidden className="size-4" />
              {create.isPending ? "Adding…" : "Add education"}
            </Button>
            <p aria-live="polite" className="text-sm text-destructive">
              {create.isError && "Could not add that education entry."}
              {remove.isError && "Could not remove that entry."}
            </p>
          </div>
        </form>
      }
    />
  );
}
