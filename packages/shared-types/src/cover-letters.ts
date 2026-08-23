/** Contracts for cover letters. */

import type { ClaimStatus } from "./resumes-engine";

/**
 * Where a letter is between being drafted and being usable.
 *
 * `EDITED` is distinct from `DRAFTED` because it changes what the claims mean:
 * they were computed against the model's words, and a human edit is not
 * re-validated. What a person writes about themselves is theirs.
 */
export type CoverLetterStatus = "DRAFTING" | "DRAFTED" | "EDITED" | "APPROVED" | "FAILED";

export interface CoverLetterClaim {
  /** The sentence, quoted from the draft. */
  text: string;
  status: ClaimStatus;
  explanation: string;
  confidence: number;
}

/** Payload of `GET`/`POST /api/v1/jobs/{id}/cover-letter`. */
export interface CoverLetter {
  id: string;
  job_id: string;
  status: CoverLetterStatus;
  /** The argument the letter was asked to make. */
  angle: string | null;
  /** The letter. Null while drafting, and null if drafting failed. */
  body: string | null;
  /**
   * The model saying the requested angle is not supported by the facts.
   *
   * Shown rather than logged: when it is set it is usually the most useful
   * thing the draft has to say.
   */
  angle_warning: string | null;
  error: string | null;
  edited_at: string | null;
  approved_at: string | null;
  created_at: string;
  /**
   * What validation concluded. Always present, never fetched separately — a
   * draft with a blocked claim is one the user must not send, and making the
   * warning optional to fetch would make it optional to see.
   */
  claims: CoverLetterClaim[];
}

/** Body of `POST /api/v1/jobs/{id}/cover-letter`. */
export interface CoverLetterDraftRequest {
  /** Omitted means the default, which deliberately takes no position. */
  angle?: string | null;
}

/** Body of `PATCH /api/v1/cover-letters/{id}`. */
export interface CoverLetterEditRequest {
  body: string;
}
