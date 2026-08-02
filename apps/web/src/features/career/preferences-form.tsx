"use client";

import type {
  CareerPreferences,
  CareerPreferencesUpdate,
  EmploymentType,
  RoleFamily,
  WorkMode,
} from "@jip/shared-types";
import { EMPLOYMENT_TYPE_LABELS, ROLE_FAMILY_LABELS, WORK_MODE_LABELS } from "@jip/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { FieldHint, Label } from "@/components/ui/label";
import {
  careerPreferencesQueryKey,
  fetchCareerPreferences,
  updateCareerPreferences,
} from "@/features/career/api";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const WORK_MODES: WorkMode[] = ["ONSITE", "HYBRID", "REMOTE"];

// Only the types a person searches for. VOLUNTEER exists on an experience
// record — you can have volunteered — but nobody sets it as what they are
// looking for, and an option nobody picks is noise in a list this short.
const EMPLOYMENT_TYPES: EmploymentType[] = [
  "FULL_TIME",
  "PART_TIME",
  "CONTRACT",
  "FREELANCE",
  "INTERNSHIP",
];

const ROLE_FAMILIES: RoleFamily[] = [
  "BACKEND",
  "FRONTEND",
  "FULL_STACK",
  "SOFTWARE",
  "AI_ML",
  "DATA_ENGINEERING",
  "COMPUTER_VISION",
  "DEVOPS",
  "CYBERSECURITY",
];

interface FormState {
  work_modes: WorkMode[];
  employment_types: EmploymentType[];
  locations: string;
  open_to_relocation: boolean | null;
  salary_min: string;
  salary_currency: string;
  excluded_role_families: RoleFamily[];
}

function toFormState(preferences: CareerPreferences): FormState {
  return {
    work_modes: [...preferences.work_modes],
    employment_types: [...preferences.employment_types],
    // One per line rather than a tag editor: a location is prose on the posting
    // side too, and a free-text list keeps the two comparable.
    locations: preferences.locations.join("\n"),
    open_to_relocation: preferences.open_to_relocation,
    // A string so the field can be genuinely empty. Coercing to 0 would record
    // "I will work for nothing" for someone who has not answered.
    salary_min: preferences.salary_min === null ? "" : String(preferences.salary_min),
    salary_currency: preferences.salary_currency ?? "",
    excluded_role_families: [...preferences.excluded_role_families],
  };
}

function parseLocations(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** Only the fields whose stored value differs from what is on screen. */
function buildUpdate(form: FormState, saved: CareerPreferences): CareerPreferencesUpdate {
  const update: CareerPreferencesUpdate = {};
  const differs = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);

  if (differs(form.work_modes, saved.work_modes)) update.work_modes = form.work_modes;
  if (differs(form.employment_types, saved.employment_types)) {
    update.employment_types = form.employment_types;
  }
  if (differs(form.excluded_role_families, saved.excluded_role_families)) {
    update.excluded_role_families = form.excluded_role_families;
  }

  const locations = parseLocations(form.locations);
  if (differs(locations, saved.locations)) update.locations = locations;

  if (form.open_to_relocation !== saved.open_to_relocation) {
    update.open_to_relocation = form.open_to_relocation;
  }

  const salary = form.salary_min.trim() === "" ? null : Number(form.salary_min);
  if (salary !== saved.salary_min) update.salary_min = salary;

  const currency = form.salary_currency.trim() === "" ? null : form.salary_currency.trim();
  if (currency !== saved.salary_currency) update.salary_currency = currency;

  return update;
}

/**
 * Career preferences.
 *
 * Every group says what reads it, and the salary group says plainly that
 * nothing does. That is the whole design brief: DEV-035 was four documents
 * describing a preference the product never stored, and the failure it left
 * behind — a value recorded and quietly ignored — is worse than the gap,
 * because the user believes it was taken into account.
 */
export function PreferencesForm() {
  const api = useApi();
  const queryClient = useQueryClient();

  const {
    data: saved,
    isPending,
    error,
  } = useQuery({
    queryKey: careerPreferencesQueryKey,
    queryFn: () => fetchCareerPreferences(api),
  });

  const [form, setForm] = useState<FormState | null>(null);

  useEffect(() => {
    if (saved) setForm(toFormState(saved));
  }, [saved]);

  const mutation = useMutation({
    mutationFn: (update: CareerPreferencesUpdate) => updateCareerPreferences(api, update),
    onSuccess: (result) => queryClient.setQueryData(careerPreferencesQueryKey, result),
  });

  // Error first, for the reason the profile form gives: on a failed load `form`
  // stays null, so checking `!form` first would show "Loading…" forever.
  if (error) {
    const unauthenticated = error instanceof ApiError && error.isUnauthenticated;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p className="font-medium text-destructive">Could not load your preferences.</p>
          <p className="text-muted-foreground">
            {unauthenticated
              ? "Your session was not accepted. Try signing out and back in."
              : error.message}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (isPending || !form || !saved) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Preferences</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading your preferences…</p>
        </CardContent>
      </Card>
    );
  }

  const update = buildUpdate(form, saved);
  const hasChanges = Object.keys(update).length > 0;

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));

  function toggle<T extends string>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (hasChanges) mutation.mutate(update);
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Where and how you will work</CardTitle>
          <CardDescription>
            Shown against each job you save, beside the match. Leaving a group empty means no
            constraint — never that you would accept nothing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Work mode</legend>
            <FieldHint>
              A posting only counts as matching when it says which it is. Most do not, and we say so
              rather than assuming.
            </FieldHint>
            <div className="flex flex-wrap gap-2 pt-1">
              {WORK_MODES.map((mode) => (
                <Toggle
                  key={mode}
                  label={WORK_MODE_LABELS[mode]}
                  pressed={form.work_modes.includes(mode)}
                  onClick={() => setField("work_modes", toggle(form.work_modes, mode))}
                />
              ))}
            </div>
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Employment type</legend>
            <div className="flex flex-wrap gap-2 pt-1">
              {EMPLOYMENT_TYPES.map((kind) => (
                <Toggle
                  key={kind}
                  label={EMPLOYMENT_TYPE_LABELS[kind]}
                  pressed={form.employment_types.includes(kind)}
                  onClick={() => setField("employment_types", toggle(form.employment_types, kind))}
                />
              ))}
            </div>
          </fieldset>

          <div className="space-y-2">
            <Label htmlFor="locations">Locations</Label>
            <FieldHint>
              One per line, written how you would say them. A posting states its location as prose
              too, so an imperfect match is reported as unconfirmed rather than as a conflict.
            </FieldHint>
            <textarea
              id="locations"
              className="min-h-24 w-full rounded-md border bg-transparent px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              value={form.locations}
              onChange={(event) => setField("locations", event.target.value)}
              placeholder={"Tel Aviv\nHaifa"}
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Relocation</legend>
            <FieldHint>
              Answering yes widens what counts as a location match. Leaving it unanswered narrows
              nothing.
            </FieldHint>
            <div className="flex flex-wrap gap-2 pt-1">
              <Toggle
                label="Open to relocating"
                pressed={form.open_to_relocation === true}
                onClick={() =>
                  setField("open_to_relocation", form.open_to_relocation === true ? null : true)
                }
              />
              <Toggle
                label="Not relocating"
                pressed={form.open_to_relocation === false}
                onClick={() =>
                  setField("open_to_relocation", form.open_to_relocation === false ? null : false)
                }
              />
            </div>
          </fieldset>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Role types to exclude</CardTitle>
          <CardDescription>
            The one preference we can check exactly: an analysed posting carries a role family, so a
            mismatch here is a real mismatch rather than an unmatched phrase.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {ROLE_FAMILIES.map((family) => (
              <Toggle
                key={family}
                label={ROLE_FAMILY_LABELS[family]}
                pressed={form.excluded_role_families.includes(family)}
                onClick={() =>
                  setField("excluded_role_families", toggle(form.excluded_role_families, family))
                }
              />
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Salary</CardTitle>
          <CardDescription>
            Recorded for your own reference, and <strong>not compared against postings</strong>.
            They state pay as free text when they state it at all, so a comparison would be a guess
            presented as arithmetic — and a job discarded on a number we invented is worse than one
            we said nothing about.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <div className="space-y-2">
            <Label htmlFor="salary_min">Minimum</Label>
            <Input
              id="salary_min"
              inputMode="numeric"
              value={form.salary_min}
              onChange={(event) =>
                setField("salary_min", event.target.value.replace(/[^0-9]/g, ""))
              }
              placeholder="25000"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="salary_currency">Currency</Label>
            <Input
              id="salary_currency"
              maxLength={3}
              className="w-24"
              value={form.salary_currency}
              onChange={(event) => setField("salary_currency", event.target.value.toUpperCase())}
              placeholder="ILS"
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!hasChanges || mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save preferences"}
        </Button>
        <p aria-live="polite" className="text-sm">
          {mutation.isError ? (
            <span className="text-destructive">
              {mutation.error instanceof Error ? mutation.error.message : "Could not save."}
            </span>
          ) : hasChanges ? (
            <span className="text-muted-foreground">Unsaved changes.</span>
          ) : mutation.isSuccess ? (
            <span className="text-muted-foreground">Saved.</span>
          ) : null}
        </p>
      </div>
    </form>
  );
}

/**
 * A two-state chip.
 *
 * `aria-pressed` rather than colour alone: `docs/08-ui-ux.md` forbids colour as
 * the only signal, and a toggle whose state is carried by a background shade is
 * exactly that.
 */
function Toggle({
  label,
  pressed,
  onClick,
}: {
  label: string;
  pressed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${
        pressed
          ? "border-primary bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted"
      }`}
    >
      {pressed ? "✓ " : ""}
      {label}
    </button>
  );
}
