"use client";

import {
  API_ROUTES,
  PROFICIENCY_LABELS,
  SKILL_CATEGORY_LABELS,
  type Proficiency,
  type SkillCategory,
  type UserSkill,
  type UserSkillCreate,
} from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldHint, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { CollectionSection } from "@/features/career/section";
import { useCollection } from "@/features/career/use-collection";
import { ApiError } from "@/lib/api";

const EMPTY: UserSkillCreate = { name: "", category: "OTHER", proficiency: null };

export function SkillsSection() {
  const { query, create, remove } = useCollection<UserSkill, UserSkillCreate>(
    ["career", "skills"],
    API_ROUTES.careerSkills,
  );
  const [draft, setDraft] = useState<UserSkillCreate>(EMPTY);

  const nameIsBlank = draft.name.trim() === "";

  return (
    <CollectionSection
      title="Skills"
      description="What you can do. Names are matched to a shared catalogue, so React and React.js count as the same skill."
      items={query.data}
      isPending={query.isPending}
      error={query.error}
      emptyMessage="No skills yet. Add the ones you would want a job match to consider."
      renderItem={(skill) => (
        <>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{skill.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {[
                SKILL_CATEGORY_LABELS[skill.category],
                skill.proficiency ? PROFICIENCY_LABELS[skill.proficiency] : null,
                skill.years_of_experience !== null ? `${skill.years_of_experience}y` : null,
                skill.last_used_year !== null ? `last used ${skill.last_used_year}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>

          <Badge variant={skill.verification_status === "USER_CONFIRMED" ? "success" : "secondary"}>
            {skill.verification_status === "USER_CONFIRMED" ? "Confirmed" : "Unconfirmed"}
          </Badge>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${skill.name}`}
            disabled={remove.isPending}
            onClick={() => remove.mutate(skill.id)}
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
            create.mutate(
              { ...draft, name: draft.name.trim() },
              { onSuccess: () => setDraft(EMPTY) },
            );
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="skill-name">Skill</Label>
              <Input
                id="skill-name"
                value={draft.name}
                maxLength={120}
                placeholder="Python"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="skill-category">Category</Label>
              <Select
                id="skill-category"
                value={draft.category ?? "OTHER"}
                onChange={(event) =>
                  setDraft({ ...draft, category: event.target.value as SkillCategory })
                }
              >
                {Object.entries(SKILL_CATEGORY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="skill-proficiency">Proficiency</Label>
              <Select
                id="skill-proficiency"
                value={draft.proficiency ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    proficiency: (event.target.value || null) as Proficiency | null,
                  })
                }
              >
                <option value="">Not specified</option>
                {Object.entries(PROFICIENCY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="skill-years">Years of experience</Label>
              <Input
                id="skill-years"
                type="number"
                min={0}
                max={80}
                value={draft.years_of_experience ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    years_of_experience:
                      event.target.value === "" ? null : Number(event.target.value),
                  })
                }
              />
              <FieldHint>Optional.</FieldHint>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={nameIsBlank || create.isPending}>
              <Plus aria-hidden className="size-4" />
              {create.isPending ? "Adding…" : "Add skill"}
            </Button>
            <p aria-live="polite" className="text-sm text-destructive">
              {create.isError &&
                (create.error instanceof ApiError && create.error.status === 409
                  ? "That skill is already in your list."
                  : "Could not add that skill.")}
              {remove.isError && "Could not remove that skill."}
            </p>
          </div>
        </form>
      }
    />
  );
}
