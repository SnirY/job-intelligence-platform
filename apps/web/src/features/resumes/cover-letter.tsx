"use client";

import type { CoverLetter, CoverLetterClaim, Job } from "@jip/shared-types";
import { Loader2, PenLine } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { StateCard } from "@/components/ui/state-card";
import { Textarea } from "@/components/ui/textarea";
import {
  useApproveCoverLetter,
  useCoverLetter,
  useDraftCoverLetter,
  useEditCoverLetter,
} from "@/features/resumes/cover-letter-api";

/**
 * The cover letter panel.
 *
 * Two rules govern what this screen may show, and both come from the engine
 * beneath it rather than from a preference about layout.
 *
 * **A blocked claim is shown, and the letter is still shown with it.**
 * `docs/06-resume-engine.md` wants the system to *ask* for a missing metric,
 * not to refuse the document — the user may know the figure is real, and the
 * fix is to add it to their profile. So a warning appears above the text and
 * approval stays available. Hiding the draft would be the system deciding it
 * knows better than the person whose career it is.
 *
 * **A human edit is not re-validated, and the screen says so.** The claims were
 * computed against the model's words. Once a person has rewritten the letter,
 * those claims describe something that is no longer on screen, and continuing
 * to show them as though they did would be the worst of both.
 */
export function CoverLetterPanel({ job }: { job: Job }) {
  const letter = useCoverLetter(job.id);
  const draft = useDraftCoverLetter(job.id);
  const [angle, setAngle] = useState("");

  const current = letter.data;
  const drafting = current?.status === "DRAFTING" || draft.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Cover letter</CardTitle>
        <CardDescription>
          Written from the evidence in your profile and nothing else. Anything it cannot support, it
          leaves out.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {letter.isPending && <StateCard>Loading…</StateCard>}

        {!letter.isPending && !current && (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="letter-angle">What should it argue? (optional)</Label>
              <Textarea
                id="letter-angle"
                rows={2}
                value={angle}
                onChange={(event) => setAngle(event.target.value)}
                placeholder="Leave blank and it will argue the strongest case your profile supports."
              />
            </div>
            <Button
              type="button"
              disabled={draft.isPending}
              onClick={() => draft.mutate({ angle: angle.trim() || null })}
            >
              <PenLine aria-hidden className="size-4" />
              Write a draft
            </Button>
            {draft.isError && (
              <p className="text-sm text-destructive">
                This job has not been matched against your profile yet, so there is nothing to write
                a letter from.
              </p>
            )}
          </div>
        )}

        {drafting && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 aria-hidden className="size-4 animate-spin" />
            Writing a draft…
          </p>
        )}

        {current?.status === "FAILED" && (
          <StateCard tone="error">{current.error ?? "That draft could not be written."}</StateCard>
        )}

        {current?.body && !drafting && <LetterBody letter={current} />}
      </CardContent>
    </Card>
  );
}

function LetterBody({ letter }: { letter: CoverLetter }) {
  const edit = useEditCoverLetter(letter.id, letter.job_id);
  const approve = useApproveCoverLetter(letter.id, letter.job_id);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(letter.body ?? "");

  // Once a person has rewritten it, the claims describe words that are no
  // longer on screen.
  const claimsDescribeThisText = letter.status !== "EDITED";
  const blocked = letter.claims.filter((claim) => claim.status === "BLOCKED");
  const unsupported = letter.claims.filter((claim) => claim.status === "UNSUPPORTED");

  return (
    <div className="space-y-4">
      {letter.angle_warning && (
        <div className="rounded-md border border-dashed p-3 text-sm">
          <p className="font-medium">About the angle you asked for</p>
          <p className="mt-1 text-muted-foreground">{letter.angle_warning}</p>
        </div>
      )}

      {claimsDescribeThisText && blocked.length > 0 && (
        <ClaimNotice
          heading={
            blocked.length === 1
              ? "One line says something your profile does not"
              : `${blocked.length} lines say something your profile does not`
          }
          body="If these are real, add them to your profile and write the draft again. The letter is yours to send either way."
          claims={blocked}
          tone="destructive"
        />
      )}

      {claimsDescribeThisText && blocked.length === 0 && unsupported.length > 0 && (
        <ClaimNotice
          heading="Worth checking before you send"
          body="These are not in your profile, which may only mean your profile is missing them."
          claims={unsupported}
          tone="muted"
        />
      )}

      {!claimsDescribeThisText && (
        <p className="text-sm text-muted-foreground">
          You have edited this letter, so the checks below no longer describe what is on screen.
          What you write about yourself is yours.
        </p>
      )}

      {editing ? (
        <div className="space-y-3">
          <Textarea rows={14} value={text} onChange={(event) => setText(event.target.value)} />
          <div className="flex gap-2">
            <Button
              type="button"
              disabled={edit.isPending || !text.trim()}
              onClick={() => edit.mutate({ body: text }, { onSuccess: () => setEditing(false) })}
            >
              Save
            </Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          {/* whitespace-pre-wrap, not markdown: this is prose, and rendering it
            as markup would give a model output a way to emit tags on our
            origin. */}
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{letter.body}</p>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
            {letter.status !== "APPROVED" && (
              <Button type="button" disabled={approve.isPending} onClick={() => approve.mutate()}>
                Looks right
              </Button>
            )}
            {letter.status === "APPROVED" && (
              <span className="text-sm text-muted-foreground">You marked this one as ready.</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ClaimNotice({
  heading,
  body,
  claims,
  tone,
}: {
  heading: string;
  body: string;
  claims: CoverLetterClaim[];
  tone: "destructive" | "muted";
}) {
  return (
    <div className="rounded-md border p-3 text-sm">
      {/* The heading carries the seriousness in words as well as its colour —
        invariant 3, and these two levels would otherwise be told apart only by
        a shade of border. */}
      <p className={tone === "destructive" ? "font-medium text-destructive" : "font-medium"}>
        {heading}
      </p>
      <p className="mt-1 text-muted-foreground">{body}</p>
      <ul className="mt-2 space-y-2">
        {claims.map((claim) => (
          <li key={claim.text} className="border-l-2 pl-3">
            <p className="italic">{claim.text}</p>
            <p className="text-muted-foreground">{claim.explanation}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
