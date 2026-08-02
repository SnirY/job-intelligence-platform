/** Contracts for the resume engine. */

/** The hierarchy from `docs/06-resume-engine.md`. */
export type ResumeFamily = "MASTER" | "BASE" | "JOB_SPECIFIC";

export const RESUME_FAMILY_LABELS: Record<ResumeFamily, string> = {
  MASTER: "Master",
  BASE: "Base",
  JOB_SPECIFIC: "Tailored",
};

/**
 * A version's lifecycle.
 *
 * USED is the point of no return: once a version has been sent, what it said is
 * a historical fact, so its content freezes.
 */
export type ResumeVersionStatus = "DRAFT" | "REVIEW" | "APPROVED" | "USED" | "ARCHIVED";

export const VERSION_STATUS_LABELS: Record<ResumeVersionStatus, string> = {
  DRAFT: "Draft",
  REVIEW: "In review",
  APPROVED: "Approved",
  USED: "Sent",
  ARCHIVED: "Archived",
};

export type ResumeSectionKind =
  | "HEADER"
  | "SUMMARY"
  | "SKILLS"
  | "EXPERIENCE"
  | "PROJECTS"
  | "EDUCATION"
  | "CERTIFICATIONS"
  | "OTHER";

export const SECTION_KIND_LABELS: Record<ResumeSectionKind, string> = {
  HEADER: "Header",
  SUMMARY: "Summary",
  SKILLS: "Skills",
  EXPERIENCE: "Experience",
  PROJECTS: "Projects",
  EDUCATION: "Education",
  CERTIFICATIONS: "Certifications",
  OTHER: "Other",
};

/** Which career table an item came from. MANUAL means no single source row. */
export type ResumeItemSource =
  "SKILL" | "EXPERIENCE" | "ACHIEVEMENT" | "PROJECT" | "EDUCATION" | "MANUAL";

export interface Resume {
  id: string;
  title: string;
  family: ResumeFamily;
  job_id: string | null;
  parent_resume_id: string | null;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeItem {
  id: string;
  text: string;
  heading: string | null;
  source_type: ResumeItemSource;
  source_entity_id: string | null;
  display_order: number;
}

export interface ResumeSection {
  id: string;
  kind: ResumeSectionKind;
  title: string | null;
  display_order: number;
  items: ResumeItem[];
}

export interface ResumeVersion {
  id: string;
  resume_id: string;
  version: number;
  parent_version_id: string | null;
  status: ResumeVersionStatus;
  label: string | null;
  used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeVersionDetail extends ResumeVersion {
  sections: ResumeSection[];
  /** Served rather than derived, so the button and the endpoint agree. */
  is_editable: boolean;
}

// --- tailoring ----------------------------------------------------------------

/** What kind of change a suggestion is. */
export type SuggestionType =
  "REWRITE" | "REORDER" | "ADD_EXISTING_ITEM" | "REMOVE" | "SHORTEN" | "EMPHASIZE";

/** The user's decision. */
export type SuggestionStatus = "PENDING" | "ACCEPTED" | "REJECTED" | "EDITED";

/**
 * How much a change could distort the truth.
 *
 * Orthogonal to `ClaimStatus`: risk is about the *kind* of edit, claim status
 * about whether what it says is *supported*. A low-risk change can still be
 * unsupported.
 */
export type SuggestionRisk = "LOW" | "MEDIUM" | "HIGH";

/**
 * What each kind of change actually does, in the user's terms.
 *
 * Shown because a REORDER proposes no new words: it moves a line. Without the
 * kind on screen, the review row rendered the original struck through above an
 * identical replacement, which reads as "delete this and put it back". Found in
 * Stage 2.8.6.
 */
export const SUGGESTION_TYPE_LABELS: Record<SuggestionType, string> = {
  REWRITE: "Reworded",
  REORDER: "Move this earlier",
  ADD_EXISTING_ITEM: "Add from your profile",
  REMOVE: "Remove for this job",
  SHORTEN: "Shortened",
  EMPHASIZE: "Reordered within the line",
};

export const RISK_LABELS: Record<SuggestionRisk, string> = {
  LOW: "Low risk",
  MEDIUM: "Worth checking",
  HIGH: "Check carefully",
};

/** Whether a claim is supported by evidence. From `docs/05-ai-and-matching.md`. */
export type ClaimStatus = "SAFE" | "REQUIRES_CONFIRMATION" | "UNSUPPORTED" | "BLOCKED";

export const CLAIM_STATUS_LABELS: Record<ClaimStatus, string> = {
  SAFE: "Supported",
  REQUIRES_CONFIRMATION: "Check this",
  UNSUPPORTED: "Not in your profile",
  BLOCKED: "Not supported",
};

export interface ResumeClaim {
  id: string;
  text: string;
  status: ClaimStatus;
  explanation: string;
  confidence: number;
}

export interface ResumeSuggestion {
  id: string;
  item_id: string | null;
  suggestion_type: SuggestionType;
  status: SuggestionStatus;
  risk: SuggestionRisk;
  original_text: string | null;
  suggested_text: string;
  final_text: string | null;
  rationale: string | null;
  display_order: number;
  claims: ResumeClaim[];
  requires_review: boolean;
  /** Accepting this would put something the profile does not support on the page. */
  is_blocked: boolean;
}

export interface SelectedItem {
  source_type: string;
  entity_id: string;
  text: string;
  heading: string | null;
  score: number;
  reasons: string[];
}

export interface SelectedSection {
  kind: string;
  items: SelectedItem[];
}

export interface ResumeStrategy {
  id: string;
  job_id: string;
  match_id: string;
  version: number;
  version_id: string | null;
  summary: string | null;
  emphasize: string[];
  reduce: string[];
  reorder_note: string | null;
  priority_projects: string[];
  /** Evidence you have that this resume does not show. A *resume* gap. */
  missing_evidence: string[];
  /** Evidence you genuinely lack. A *career* gap, which no rewriting fixes. */
  career_gaps: string[];
  selection: {
    sections?: SelectedSection[];
    withheld_unverified?: { text: string; verification_status: string }[];
  };
  model: string | null;
  prompt_version: string | null;
  warnings: string[];
  created_at: string;
}

/** Payload of `GET`/`POST /api/v1/jobs/{id}/resume-strategies`. */
export interface ResumeStrategyView {
  strategy: ResumeStrategy | null;
  suggestions: ResumeSuggestion[];
  blocked_count: number;
  can_create: boolean;
  blocking_reason: string | null;
  /**
   * Whether the rewriter has run, whatever it found.
   *
   * An empty `suggestions` means two different things, and the screen showed
   * one message for both: *not asked for yet*, and *asked for, and there was
   * nothing worth changing*. The second is a legitimate answer — the rewriter
   * is told to leave a good line alone — and reporting it as "No suggestions
   * yet" made a completed run look like a button that had not been pressed.
   */
  suggestions_generated: boolean;
}

export interface FinalizeResult {
  version_id: string;
  version: number;
  applied: number;
}
