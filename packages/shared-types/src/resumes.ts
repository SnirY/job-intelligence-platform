/** Contracts for the resume import API. */

/** Statuses from `docs/03-domain-model.md`. */
export type ProcessingJobStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

/** Where inside a job the work currently is. */
export type ProcessingStep = "QUEUED" | "EXTRACTING" | "PARSING" | "COMPLETED";

/** How far the document has progressed. */
export type DocumentStatus =
  "UPLOADED" | "EXTRACTING" | "EXTRACTED" | "PARSING" | "PARSED" | "CONFIRMED" | "FAILED";

/** The failure taxonomy from `docs/10-api-contracts.md`. */
export type AIFailureCode =
  | "PROVIDER_ERROR"
  | "RATE_LIMIT"
  | "TIMEOUT"
  | "INVALID_OUTPUT"
  | "VALIDATION_FAILURE"
  | "CONTENT_UNAVAILABLE";

export interface ProcessingJob {
  id: string;
  status: ProcessingJobStatus;
  step: ProcessingStep;
  attempts: number;
  max_attempts: number;
  error_code: AIFailureCode | string | null;
  error_message: string | null;
  /** Whether the retry endpoint will accept this job. Decided when the failure
   * was classified, so the button is only shown when it can actually help. */
  is_retriable: boolean;
}

export interface SourceDocument {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  extraction_error: string | null;
  created_at: string;
}

/** Payload of `POST /api/v1/resumes/import` — the documented 202 contract. */
export interface ImportAccepted {
  source_document_id: string;
  processing_job_id: string;
  status: ProcessingJobStatus;
}

export interface ImportSummary {
  document: SourceDocument;
  job: ProcessingJob | null;
}

/** One approve destination. */
export type CandidateType =
  "SKILL" | "EXPERIENCE" | "EXPERIENCE_ACHIEVEMENT" | "PROJECT" | "PROJECT_SKILL" | "EDUCATION";

export const CANDIDATE_TYPE_LABELS: Record<CandidateType, string> = {
  SKILL: "Skills",
  EXPERIENCE: "Experience",
  EXPERIENCE_ACHIEVEMENT: "Achievements",
  PROJECT: "Projects",
  PROJECT_SKILL: "Technologies",
  EDUCATION: "Education",
};

/** The order the review screen presents candidates in, parents before children. */
export const CANDIDATE_TYPE_ORDER: readonly CandidateType[] = [
  "EXPERIENCE",
  "PROJECT",
  "SKILL",
  "EDUCATION",
] as const;

export type CandidateDecision = "PENDING" | "ACCEPTED" | "EDITED" | "IGNORED";

/**
 * One reviewable fact the parser proposed.
 *
 * `payload` is untyped because its shape depends on `candidate_type`; the
 * backend validated it against `ResumeParseResult` before storing it. Read it
 * through the helpers in `features/resume-import/candidates.ts` rather than
 * indexing it directly.
 */
export interface ExtractionItem {
  id: string;
  candidate_type: CandidateType;
  parent_item_id: string | null;
  display_order: number;
  payload: Record<string, unknown>;
  edited_payload: Record<string, unknown> | null;
  /** 0-100, or null when the parser did not say. Uncertainty, not accuracy. */
  confidence: number | null;
  /** The span of the resume this came from, when it could be verified against
   * the document. Null when the parser quoted something that was not there. */
  source_text: string | null;
  decision: CandidateDecision;
  target_entity_type: string | null;
  target_entity_id: string | null;
}

export interface Extraction {
  id: string;
  version: number;
  prompt_version: string;
  model: string;
  provider: string;
  /** What validation dropped or could not trust. Shown so the user is told,
   * rather than left wondering why a line from their resume is missing. */
  warnings: string[];
  confirmed_at: string | null;
  items: ExtractionItem[];
}

/** Payload of `GET /api/v1/resumes/imports/{id}/extraction`. */
export interface ExtractionReview {
  document: SourceDocument;
  job: ProcessingJob | null;
  /** Null while processing is still running. */
  extraction: Extraction | null;
}

export type ConfirmAction = "ACCEPT" | "EDIT" | "IGNORE";

export interface ConfirmDecision {
  item_id: string;
  action: ConfirmAction;
  /** Only for EDIT. Merged over the extracted payload. */
  payload?: Record<string, unknown>;
}

export type ConfirmOutcome =
  "CREATED" | "LINKED" | "ALREADY_APPLIED" | "IGNORED" | "SKIPPED_PARENT_NOT_ACCEPTED" | "INVALID";

export interface AppliedItem {
  item_id: string;
  candidate_type: CandidateType;
  outcome: ConfirmOutcome;
  target_entity_type: string | null;
  target_entity_id: string | null;
  detail: string | null;
}

export interface ConfirmationResult {
  applied: AppliedItem[];
  created_count: number;
  remaining_pending: number;
}

export interface SignedUrl {
  url: string;
  expires_in_seconds: number;
}

/** Flags business validation attaches to a candidate it could not verify. */
export type CandidateFlag = "QUOTE_NOT_FOUND" | "UNSUPPORTED_NUMBERS";

export const CANDIDATE_FLAG_LABELS: Record<CandidateFlag, string> = {
  QUOTE_NOT_FOUND: "Could not find this in your document",
  UNSUPPORTED_NUMBERS: "Contains a number your document does not",
};
