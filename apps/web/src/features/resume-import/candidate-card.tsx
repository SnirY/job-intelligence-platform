"use client";

import { CANDIDATE_FLAG_LABELS, type ConfirmAction, type ExtractionItem } from "@jip/shared-types";
import { AlertTriangle, Check, Pencil, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  candidateDetail,
  candidateTitle,
  datePrecisionNote,
  editableFields,
  effectivePayload,
  readFlags,
} from "@/features/resume-import/candidates";

export interface CandidateDecisionState {
  action: ConfirmAction;
  payload?: Record<string, unknown>;
}

interface CandidateCardProps {
  item: ExtractionItem;
  decision: CandidateDecisionState;
  onChange: (next: CandidateDecisionState) => void;
  children?: React.ReactNode;
  /** Rendered smaller and indented, for achievements and technologies. */
  nested?: boolean;
}

/**
 * One review candidate with its three actions.
 *
 * Everything on this card is a *proposal*. The visual language deliberately
 * differs from the confirmed profile sections: nothing here is styled as a
 * fact until the user has accepted it.
 */
export function CandidateCard({
  item,
  decision,
  onChange,
  children,
  nested = false,
}: CandidateCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const flags = readFlags(item);
  const precision = datePrecisionNote(item);
  const alreadyApplied = item.target_entity_id !== null;

  function setAction(action: ConfirmAction) {
    onChange({ action, payload: decision.payload });
    if (action !== "EDIT") setIsEditing(false);
  }

  return (
    <li
      className={[
        "space-y-3 rounded-md border p-3",
        nested ? "ml-6 border-dashed" : "",
        decision.action === "IGNORE" ? "opacity-50" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className={nested ? "text-sm" : "text-sm font-medium"}>{candidateTitle(item)}</p>
          {candidateDetail(item) && (
            <p className="truncate text-xs text-muted-foreground">{candidateDetail(item)}</p>
          )}
        </div>

        {item.confidence !== null && (
          <Badge variant={item.confidence >= 70 ? "secondary" : "outline"}>
            {/* Labelled as certainty, not accuracy: docs/05-ai-and-matching.md
                treats a confident model as still an untrusted one. */}
            {item.confidence}% sure
          </Badge>
        )}

        {alreadyApplied && <Badge variant="success">Already on your profile</Badge>}
      </div>

      {flags.length > 0 && (
        <ul className="space-y-1">
          {flags.map((flag) => (
            <li key={flag} className="flex items-start gap-2 text-xs text-destructive">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {CANDIDATE_FLAG_LABELS[flag]}
            </li>
          ))}
        </ul>
      )}

      {precision && <p className="text-xs text-muted-foreground">{precision}</p>}

      {item.source_text && (
        <blockquote className="border-l-2 pl-3 text-xs italic text-muted-foreground">
          “{item.source_text}”
        </blockquote>
      )}

      <div className="flex flex-wrap gap-2">
        <ActionButton
          label="Accept"
          icon={<Check aria-hidden className="size-4" />}
          active={decision.action === "ACCEPT"}
          onClick={() => setAction("ACCEPT")}
        />
        <ActionButton
          label="Edit"
          icon={<Pencil aria-hidden className="size-4" />}
          active={decision.action === "EDIT"}
          onClick={() => {
            setAction("EDIT");
            setIsEditing(true);
          }}
        />
        <ActionButton
          label="Ignore"
          icon={<X aria-hidden className="size-4" />}
          active={decision.action === "IGNORE"}
          onClick={() => setAction("IGNORE")}
        />
      </div>

      {isEditing && (
        <EditFields
          item={item}
          values={decision.payload ?? {}}
          onChange={(payload) => onChange({ action: "EDIT", payload })}
        />
      )}

      {children}
    </li>
  );
}

function ActionButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={active ? "default" : "outline"}
      aria-pressed={active}
      onClick={onClick}
    >
      {icon}
      {label}
    </Button>
  );
}

function EditFields({
  item,
  values,
  onChange,
}: {
  item: ExtractionItem;
  values: Record<string, unknown>;
  onChange: (payload: Record<string, unknown>) => void;
}) {
  const base = effectivePayload(item);

  return (
    <div className="grid gap-3 rounded-md bg-muted/40 p-3 sm:grid-cols-2">
      {editableFields(item.candidate_type).map((field) => {
        const current = values[field] ?? base[field] ?? "";
        const inputId = `${item.id}-${field}`;
        return (
          <div key={field} className="space-y-1">
            <Label htmlFor={inputId} className="text-xs capitalize">
              {field.replace(/_/g, " ")}
            </Label>
            <Input
              id={inputId}
              value={typeof current === "string" ? current : ""}
              onChange={(event) => onChange({ ...values, [field]: event.target.value })}
            />
          </div>
        );
      })}
    </div>
  );
}
