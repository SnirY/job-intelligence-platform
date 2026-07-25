"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CareerProfile, CareerProfileUpdate, ProfileLink } from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldHint, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  careerProfileQueryKey,
  fetchCareerProfile,
  updateCareerProfile,
} from "@/features/career/api";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const MAX_LINKS = 10;

interface FormState {
  headline: string;
  professional_summary: string;
  years_of_experience: string;
  current_location: string;
  links: ProfileLink[];
}

function toFormState(profile: CareerProfile): FormState {
  return {
    headline: profile.headline ?? "",
    professional_summary: profile.professional_summary ?? "",
    // Kept as a string so the input can be genuinely empty. Coercing to 0 would
    // record "no experience" for someone who simply has not answered yet.
    years_of_experience:
      profile.years_of_experience === null ? "" : String(profile.years_of_experience),
    current_location: profile.current_location ?? "",
    links: profile.links.map((link) => ({ ...link })),
  };
}

/** Fields whose stored value differs from what is on screen. */
function buildUpdate(form: FormState, profile: CareerProfile): CareerProfileUpdate {
  const update: CareerProfileUpdate = {};

  const text = (value: string) => (value.trim() === "" ? null : value.trim());

  if (text(form.headline) !== profile.headline) update.headline = text(form.headline);
  if (text(form.professional_summary) !== profile.professional_summary) {
    update.professional_summary = text(form.professional_summary);
  }
  if (text(form.current_location) !== profile.current_location) {
    update.current_location = text(form.current_location);
  }

  const years = form.years_of_experience.trim() === "" ? null : Number(form.years_of_experience);
  if (years !== profile.years_of_experience) update.years_of_experience = years;

  const cleanedLinks = form.links
    .map((link) => ({ label: link.label.trim(), url: link.url.trim() }))
    .filter((link) => link.label !== "" || link.url !== "");
  if (JSON.stringify(cleanedLinks) !== JSON.stringify(profile.links)) {
    update.links = cleanedLinks;
  }

  return update;
}

export function ProfileBasicsForm() {
  const api = useApi();
  const queryClient = useQueryClient();

  const {
    data: profile,
    isPending,
    error,
  } = useQuery({
    queryKey: careerProfileQueryKey,
    queryFn: () => fetchCareerProfile(api),
  });

  const [form, setForm] = useState<FormState | null>(null);

  // Seed the form once the profile arrives, and re-seed after a save so the
  // inputs reflect what the server actually stored — including any trimming.
  useEffect(() => {
    if (profile) setForm(toFormState(profile));
  }, [profile]);

  const mutation = useMutation({
    mutationFn: (update: CareerProfileUpdate) => updateCareerProfile(api, update),
    onSuccess: (saved) => {
      queryClient.setQueryData(careerProfileQueryKey, saved);
    },
  });

  // Error is checked first on purpose. When the query fails, `form` stays null
  // because no profile ever arrived — testing `!form` first would leave a
  // failed load showing "Loading…" indefinitely.
  if (error) {
    const unauthenticated = error instanceof ApiError && error.isUnauthenticated;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Profile basics</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p className="font-medium text-destructive">Could not load your profile.</p>
          <p className="text-muted-foreground">
            {unauthenticated
              ? "Your session was not accepted. Try signing out and back in."
              : error.message}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (isPending || !form || !profile) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Profile basics</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading your profile…</p>
        </CardContent>
      </Card>
    );
  }

  const update = buildUpdate(form, profile);
  const hasChanges = Object.keys(update).length > 0;
  const tooManyLinks = form.links.length > MAX_LINKS;

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));

  const setLink = (index: number, patch: Partial<ProfileLink>) =>
    setForm((current) =>
      current
        ? {
            ...current,
            links: current.links.map((link, i) => (i === index ? { ...link, ...patch } : link)),
          }
        : current,
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Profile basics</CardTitle>
        <CardDescription>
          How you describe yourself professionally. Everything here is yours to edit — nothing is
          generated.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form
          className="space-y-6"
          onSubmit={(event) => {
            event.preventDefault();
            if (hasChanges && !tooManyLinks) mutation.mutate(update);
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="headline">Headline</Label>
            <Input
              id="headline"
              value={form.headline}
              maxLength={200}
              placeholder="Backend engineer focused on Python and distributed systems"
              onChange={(event) => setField("headline", event.target.value)}
              aria-describedby="headline-hint"
            />
            <FieldHint id="headline-hint">One line. What you do, not what you want.</FieldHint>
          </div>

          <div className="space-y-2">
            <Label htmlFor="summary">Professional summary</Label>
            <Textarea
              id="summary"
              value={form.professional_summary}
              maxLength={5000}
              rows={5}
              placeholder="What you have built, the problems you work on, and where your depth is."
              onChange={(event) => setField("professional_summary", event.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="years">Years of experience</Label>
              <Input
                id="years"
                type="number"
                min={0}
                max={80}
                inputMode="numeric"
                value={form.years_of_experience}
                placeholder="3"
                onChange={(event) => setField("years_of_experience", event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="location">Current location</Label>
              <Input
                id="location"
                value={form.current_location}
                maxLength={200}
                placeholder="Tel Aviv, Israel"
                onChange={(event) => setField("current_location", event.target.value)}
              />
            </div>
          </div>

          <fieldset className="space-y-3">
            <legend className="text-sm font-medium">Links</legend>

            {form.links.length === 0 ? (
              <FieldHint>No links yet. Add a GitHub profile, portfolio, or LinkedIn.</FieldHint>
            ) : (
              <ul className="space-y-2">
                {form.links.map((link, index) => (
                  <li key={index} className="flex flex-wrap items-start gap-2 sm:flex-nowrap">
                    <Input
                      aria-label={`Link ${index + 1} label`}
                      className="sm:max-w-40"
                      value={link.label}
                      maxLength={60}
                      placeholder="GitHub"
                      onChange={(event) => setLink(index, { label: event.target.value })}
                    />
                    <Input
                      aria-label={`Link ${index + 1} URL`}
                      type="url"
                      value={link.url}
                      placeholder="https://github.com/you"
                      onChange={(event) => setLink(index, { url: event.target.value })}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove link ${index + 1}`}
                      onClick={() =>
                        setForm((current) =>
                          current
                            ? { ...current, links: current.links.filter((_, i) => i !== index) }
                            : current,
                        )
                      }
                    >
                      <Trash2 aria-hidden className="size-4" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}

            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={form.links.length >= MAX_LINKS}
              onClick={() =>
                setForm((current) =>
                  current
                    ? { ...current, links: [...current.links, { label: "", url: "" }] }
                    : current,
                )
              }
            >
              <Plus aria-hidden className="size-4" />
              Add link
            </Button>
            {tooManyLinks && <FieldHint tone="error">At most {MAX_LINKS} links.</FieldHint>}
          </fieldset>

          <div className="flex flex-wrap items-center gap-3 border-t pt-4">
            <Button type="submit" disabled={!hasChanges || mutation.isPending || tooManyLinks}>
              {mutation.isPending ? "Saving…" : "Save changes"}
            </Button>

            {/*
              Status is announced politely so a screen-reader user learns the
              save succeeded; a visual-only confirmation would not reach them.
            */}
            <p aria-live="polite" className="text-sm">
              {mutation.isError ? (
                <span className="text-destructive">
                  {mutation.error instanceof Error
                    ? mutation.error.message
                    : "Could not save your changes."}
                </span>
              ) : mutation.isSuccess && !hasChanges ? (
                <span className="text-muted-foreground">Saved.</span>
              ) : hasChanges ? (
                <span className="text-muted-foreground">Unsaved changes.</span>
              ) : null}
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
