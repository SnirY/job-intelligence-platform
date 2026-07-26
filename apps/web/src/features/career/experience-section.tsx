"use client";

import {
  API_ROUTES,
  EMPLOYMENT_TYPE_LABELS,
  type EmploymentType,
  type Experience,
  type ExperienceCreate,
} from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { CollectionSection, formatDateRange } from "@/features/career/section";
import { useCollection } from "@/features/career/use-collection";

const EMPTY: ExperienceCreate = {
  company: "",
  title: "",
  employment_type: null,
  location: "",
  start_date: "",
  end_date: "",
  is_current: false,
  description: "",
};

/** Strip empty strings so the API sees absent rather than blank. */
function toPayload(draft: ExperienceCreate): ExperienceCreate {
  return {
    company: draft.company.trim(),
    title: draft.title.trim(),
    employment_type: draft.employment_type || null,
    location: draft.location?.trim() || null,
    start_date: draft.start_date || null,
    // A current role must not carry an end date — the API rejects that pairing.
    end_date: draft.is_current ? null : draft.end_date || null,
    is_current: draft.is_current,
    description: draft.description?.trim() || null,
  };
}

export function ExperienceSection() {
  const { query, create, remove } = useCollection<Experience, ExperienceCreate>(
    ["career", "experiences"],
    API_ROUTES.careerExperiences,
  );
  const [draft, setDraft] = useState<ExperienceCreate>(EMPTY);

  const incomplete = draft.company.trim() === "" || draft.title.trim() === "";

  return (
    <CollectionSection
      title="Experience"
      description="Roles you have held. This is the evidence a match traces back to."
      items={query.data}
      isPending={query.isPending}
      error={query.error}
      emptyMessage="No experience yet. Add the roles you would put on a resume."
      renderItem={(record) => (
        <>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {record.title} · {record.company}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {[
                formatDateRange(record.start_date, record.end_date, record.is_current),
                record.employment_type ? EMPLOYMENT_TYPE_LABELS[record.employment_type] : null,
                record.location,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${record.title} at ${record.company}`}
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
            if (incomplete) return;
            create.mutate(toPayload(draft), { onSuccess: () => setDraft(EMPTY) });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="exp-title">Title</Label>
              <Input
                id="exp-title"
                value={draft.title}
                maxLength={200}
                placeholder="Backend Engineer"
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="exp-company">Company</Label>
              <Input
                id="exp-company"
                value={draft.company}
                maxLength={200}
                placeholder="Acme"
                onChange={(event) => setDraft({ ...draft, company: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="exp-type">Employment type</Label>
              <Select
                id="exp-type"
                value={draft.employment_type ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    employment_type: (event.target.value || null) as EmploymentType | null,
                  })
                }
              >
                <option value="">Not specified</option>
                {Object.entries(EMPLOYMENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="exp-location">Location</Label>
              <Input
                id="exp-location"
                value={draft.location ?? ""}
                maxLength={200}
                placeholder="Tel Aviv"
                onChange={(event) => setDraft({ ...draft, location: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="exp-start">Start date</Label>
              <Input
                id="exp-start"
                type="date"
                value={draft.start_date ?? ""}
                onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="exp-end">End date</Label>
              <Input
                id="exp-end"
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
                I currently work here
              </label>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="exp-description">Description</Label>
            <Textarea
              id="exp-description"
              rows={3}
              maxLength={5000}
              value={draft.description ?? ""}
              placeholder="What you owned, and what you actually built."
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={incomplete || create.isPending}>
              <Plus aria-hidden className="size-4" />
              {create.isPending ? "Adding…" : "Add experience"}
            </Button>
            <p aria-live="polite" className="text-sm text-destructive">
              {create.isError && "Could not add that experience."}
              {remove.isError && "Could not remove that experience."}
            </p>
          </div>
        </form>
      }
    />
  );
}
