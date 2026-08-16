"use client";

import { API_ROUTES, type Certification, type CertificationCreate } from "@jip/shared-types";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldHint, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { CollectionSection } from "@/features/career/section";
import { useCollection, useDraft } from "@/features/career/use-collection";

const EMPTY: CertificationCreate = {
  name: "",
  issuer: "",
  issued_on: "",
  expires_on: "",
  credential_id: "",
  credential_url: "",
};

function toPayload(draft: CertificationCreate): CertificationCreate {
  return {
    name: draft.name.trim(),
    issuer: draft.issuer.trim(),
    issued_on: draft.issued_on || null,
    expires_on: draft.expires_on || null,
    credential_id: draft.credential_id?.trim() || null,
    credential_url: draft.credential_url?.trim() || null,
  };
}

/** A stored record back into the shape the form edits. */
function toDraft(record: Certification): CertificationCreate {
  return {
    name: record.name,
    issuer: record.issuer,
    issued_on: record.issued_on ?? "",
    expires_on: record.expires_on ?? "",
    credential_id: record.credential_id ?? "",
    credential_url: record.credential_url ?? "",
  };
}

/**
 * Whether the credential is still in date.
 *
 * A null `expires_on` means it does not expire, never "expiry unknown" — the
 * same reading the matcher uses. Getting this backwards would put an "Expired"
 * badge on a permanent credential.
 */
function hasLapsed(record: Certification): boolean {
  if (!record.expires_on) return false;
  return new Date(record.expires_on) < new Date();
}

/**
 * Certifications on the career profile.
 *
 * DEV-052. Named in `docs/01` beside the other collections, in `docs/03` as an
 * evidence source, and twice in `docs/06` as a resume section — and built in
 * none of them beyond a free-text box in the resume editor. Its absence was not
 * only a gap in the profile: with no CERTIFICATION requirement type, a posting
 * demanding one was read as EDUCATION, and a user who held it was told their
 * education did not appear to cover it.
 */
export function CertificationsSection() {
  const { query, create, remove, update } = useCollection<Certification, CertificationCreate>(
    ["career", "certifications"],
    API_ROUTES.careerCertifications,
  );
  const { draft, setDraft, editingId, isEditing, edit, reset } = useDraft(EMPTY);

  const required = draft.name.trim() === "" || draft.issuer.trim() === "";
  const saving = create.isPending || update.isPending;
  const expiryBeforeIssue =
    !!draft.issued_on && !!draft.expires_on && draft.expires_on < draft.issued_on;

  return (
    <CollectionSection
      title="Certifications"
      description="Credentials awarded by an issuer — AWS, Cisco, PMI, and the like. A posting asking for one is matched against these, not against your degree."
      items={query.data}
      isPending={query.isPending}
      error={query.error}
      emptyMessage="No certifications yet. Add any credential you hold, including ones that have expired — an expired certification still counts for something."
      renderItem={(record) => (
        <>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{record.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {[
                record.issuer,
                record.issued_on ? `issued ${record.issued_on.slice(0, 7)}` : null,
                record.expires_on ? `expires ${record.expires_on.slice(0, 7)}` : "no expiry",
                record.credential_id,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>

          {hasLapsed(record) && <Badge variant="secondary">Expired</Badge>}

          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Edit ${record.name}`}
            onClick={() => edit(record.id, toDraft(record))}
          >
            <Pencil aria-hidden className="size-4" />
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${record.name}`}
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
            if (required || expiryBeforeIssue) return;
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
              <Label htmlFor="cert-name">Certification</Label>
              <Input
                id="cert-name"
                value={draft.name}
                maxLength={200}
                placeholder="AWS Certified Solutions Architect – Associate"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
              <FieldHint>Write it as the issuer does — postings usually quote that name.</FieldHint>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cert-issuer">Issuer</Label>
              <Input
                id="cert-issuer"
                value={draft.issuer}
                maxLength={200}
                placeholder="Amazon Web Services"
                onChange={(event) => setDraft({ ...draft, issuer: event.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cert-issued">Issued on</Label>
              <Input
                id="cert-issued"
                type="date"
                value={draft.issued_on ?? ""}
                onChange={(event) => setDraft({ ...draft, issued_on: event.target.value })}
              />
              <FieldHint>Optional.</FieldHint>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cert-expires">Expires on</Label>
              <Input
                id="cert-expires"
                type="date"
                value={draft.expires_on ?? ""}
                onChange={(event) => setDraft({ ...draft, expires_on: event.target.value })}
              />
              <FieldHint>Leave empty if it does not expire.</FieldHint>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cert-credential">Credential ID</Label>
              <Input
                id="cert-credential"
                value={draft.credential_id ?? ""}
                maxLength={200}
                placeholder="ABCD-1234"
                onChange={(event) => setDraft({ ...draft, credential_id: event.target.value })}
              />
              <FieldHint>Optional.</FieldHint>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cert-url">Verification link</Label>
              <Input
                id="cert-url"
                type="url"
                value={draft.credential_url ?? ""}
                placeholder="https://…"
                onChange={(event) => setDraft({ ...draft, credential_url: event.target.value })}
              />
              <FieldHint>Optional.</FieldHint>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={required || expiryBeforeIssue || saving}>
              {isEditing ? (
                <Pencil aria-hidden className="size-4" />
              ) : (
                <Plus aria-hidden className="size-4" />
              )}
              {saving ? "Saving…" : isEditing ? "Save changes" : "Add certification"}
            </Button>
            {isEditing && (
              <Button type="button" variant="ghost" onClick={reset}>
                Cancel
              </Button>
            )}
            <p aria-live="polite" className="text-sm text-destructive">
              {expiryBeforeIssue && "That expiry date is before the issue date."}
              {create.isError && "Could not add that certification."}
              {update.isError && "Could not save those changes."}
              {remove.isError && "Could not remove that certification."}
            </p>
          </div>
        </form>
      }
    />
  );
}
