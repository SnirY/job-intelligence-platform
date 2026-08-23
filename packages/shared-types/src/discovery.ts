/** Contracts for board discovery. */

/**
 * One company's board on one provider, that this user watches.
 *
 * These endpoints are per-company — there is no global search across
 * Greenhouse — so discovery means "watch these companies", which is a narrower
 * promise than "search the market" and the only one the public APIs keep.
 */
export interface WatchedBoard {
  id: string;
  provider: string;
  token: string;
  /** What to call the company. Lever and Ashby never say, so without this a
   * posting is attributed to a slug. */
  label: string | null;
  /** Paused rather than removed. A paused board keeps what it already found. */
  paused_at: string | null;
  last_scanned_at: string | null;
  /**
   * Why the last scan of *this* board failed, in words safe to show.
   *
   * Per board rather than per run. "We read four of your five" is only
   * actionable if the screen can name the fifth, and an aggregate would let a
   * company quietly stop being watched.
   */
  last_error: string | null;
  created_at: string;
}

/** Body of `POST /api/v1/discovery/boards`. */
export interface WatchedBoardCreate {
  provider: string;
  token: string;
  label?: string | null;
}

/**
 * A posting a scan found, before anyone decided anything about it.
 *
 * Deliberately carries no score, no requirements, no seniority and no role
 * family. Those are readings and they come from the analysis pipeline, which a
 * posting reaches only after a person promotes it into a job.
 */
export interface DiscoveredPosting {
  id: string;
  provider: string;
  board: string;
  title: string;
  url: string;
  company: string | null;
  location: string | null;
  /** When the board says it was published. Null when the board does not say —
   * which is not the same as today. */
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  /** Whether there is posting text. The text itself is not shipped in a list. */
  has_description: boolean;
}

/** Response of `POST /api/v1/discovery/scan`. The scan has not run yet. */
export interface ScanQueued {
  /** How many boards it will read. Zero is a real answer and the screen says so
   * rather than implying work is happening. */
  boards: number;
}

/** Body of `POST /api/v1/discovery/postings/{id}/promote`. */
export interface PromoteRequest {
  /** The explicit create-anyway path, exactly as `POST /jobs` has it. A board
   * listing something pasted last week is a normal case here. */
  allow_duplicate?: boolean;
}

/** Response of a successful promote: the job it became. */
export interface PromotedPosting {
  job_id: string;
}

export const PROVIDER_LABELS: Record<string, string> = {
  greenhouse: "Greenhouse",
  ashby: "Ashby",
  lever: "Lever",
};

/** A provider's display name, falling back to whatever the API called it.
 *
 * A lookup rather than a hardcoded union, because the set of providers grows
 * with `packages/job-sources` and the API is the authority on which exist. A
 * new one should appear in the form the day it is added, not the day the
 * frontend is updated.
 */
export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}
