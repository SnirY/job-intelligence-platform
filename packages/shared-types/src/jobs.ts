/** Contracts for the job workspace API. */

import type { EmploymentType, PreferenceFit, Seniority } from "./career";

/** How a job got into the workspace. From `docs/10-api-contracts.md`. */
export type JobImportMethod = "PASTED_DESCRIPTION" | "URL" | "MANUAL";

export const IMPORT_METHOD_LABELS: Record<JobImportMethod, string> = {
  PASTED_DESCRIPTION: "Pasted",
  URL: "From a link",
  MANUAL: "Added by hand",
};

/**
 * Where the job is in the pipeline.
 *
 * Follows Flow 3 in `docs/02-user-flows.md` as far as this phase reaches.
 * MATCHING and READY belong to Phase 6 and are deliberately absent — a status
 * nothing can set is a promise the UI would render and the backend could never
 * fulfil.
 *
 * The two failure members are distinct. FAILED means there is no content, and
 * the user is offered a paste box. ANALYSIS_FAILED means the content is fine
 * and interpreting it did not work, where a paste box would be telling someone
 * to re-enter text that is already there.
 */
export type JobStatus =
  "FETCHING" | "RAW" | "PARSING" | "ANALYZING" | "ANALYZED" | "FAILED" | "ANALYSIS_FAILED";

/** The two steps an analysis passes through, in order. */
export type RunningAnalysisStatus = Extract<JobStatus, "PARSING" | "ANALYZING">;

/** Whether an analysis is running right now.
 *
 * A type guard rather than a plain predicate so a caller that has checked can
 * then say *which* step is running without re-narrowing by hand.
 */
export function isAnalysisRunning(status: JobStatus): status is RunningAnalysisStatus {
  return status === "PARSING" || status === "ANALYZING";
}

export type WorkMode = "ONSITE" | "HYBRID" | "REMOTE";

export const WORK_MODE_LABELS: Record<WorkMode, string> = {
  ONSITE: "On-site",
  HYBRID: "Hybrid",
  REMOTE: "Remote",
};

/** A job as the detail screen shows it. */
export interface Job {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  work_mode: WorkMode | null;
  employment_type: EmploymentType | null;
  seniority: Seniority | null;
  role_family: string | null;
  description: string | null;
  source_url: string | null;
  import_method: JobImportMethod;
  status: JobStatus;
  notes: string | null;
  salary_text: string | null;
  /** Why a URL import failed, in words safe to show. */
  fetch_error: string | null;
  archived_at: string | null;
  /**
   * When a check last found the posting still answering.
   *
   * Null means no check has concluded anything — not that the posting is
   * closed, and not that it is open. A check that could not reach the server
   * writes nothing, so these two never carry a guess.
   */
  last_seen_alive_at: string | null;
  /** When a check first found the posting gone. Not moved by later checks. */
  closed_detected_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * A job as the list shows it.
 *
 * Without the description: fifty jobs would otherwise ship a megabyte of text
 * nothing on screen displays.
 */
export interface JobSummary {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  work_mode: WorkMode | null;
  employment_type: EmploymentType | null;
  seniority: Seniority | null;
  status: JobStatus;
  import_method: JobImportMethod;
  source_url: string | null;
  archived_at: string | null;
  created_at: string;
  has_description: boolean;

  /**
   * How the job scored, or null when no match has been computed.
   *
   * Null is not zero. Zero would be a claim about the candidate; null is a
   * statement about our data, and the screen renders it as a dash. See
   * `docs/05-ai-and-matching.md`.
   */
  score: number | null;

  /**
   * The words that travel with the score. Never rebuilt from the number by a
   * screen — the figure has to appear beside the word "alignment", and a label
   * assembled at the call site is a label that can drift into "match" or
   * "chance".
   */
  alignment_label: string | null;

  /** The score was computed against inputs that have since moved. */
  is_stale: boolean;

  /**
   * How many requirements landed in each `MatchStatus`, for drawing a coverage
   * summary without fetching the requirements themselves.
   *
   * A missing key means zero, so the number of entries here is not the number
   * of categories. Empty when there is no match — a row with no score has no
   * counts that are missing, and the dash already says that.
   */
  status_counts: Record<string, number>;

  /** The denominator. A count without one is a percentage in disguise. */
  total_requirements: number;
}

/** One import attempt, exactly as it happened. */
export interface JobImportRecord {
  id: string;
  import_method: JobImportMethod;
  source_url: string | null;
  final_url: string | null;
  redirect_chain: string[];
  content_type: string | null;
  http_status: number | null;
  content_bytes: number | null;
  error: string | null;
  error_code: string | null;
  imported_at: string | null;
}

/**
 * Payload of `GET /api/v1/jobs/{id}/source`.
 *
 * What arrived, as it arrived — distinct from the job's current description,
 * which the user may have edited.
 */
export interface JobSource {
  job_id: string;
  import_method: JobImportMethod;
  source_url: string | null;
  original_description: string | null;
  raw_content: string | null;
  extracted_text: string | null;
  imports: JobImportRecord[];
}

/** Body of `POST /api/v1/jobs`. */
export interface JobCreate {
  import_method: JobImportMethod;
  title?: string | null;
  company?: string | null;
  location?: string | null;
  work_mode?: WorkMode | null;
  employment_type?: EmploymentType | null;
  seniority?: Seniority | null;
  role_family?: string | null;
  description?: string | null;
  source_url?: string | null;
  notes?: string | null;
  salary_text?: string | null;
  /**
   * The explicit create-anyway path.
   *
   * A possible duplicate answers 409 with the existing job; the user
   * re-submits with this set. Never the default.
   */
  allow_duplicate?: boolean;
}

/** Body of `PATCH /api/v1/jobs/{id}`. Omitted keys are left alone. */
export type JobUpdate = Partial<Omit<JobCreate, "import_method" | "allow_duplicate">>;

/** Why the API thinks a submission is a duplicate. */
export type DuplicateReason = "SAME_URL" | "SAME_CONTENT";

export const DUPLICATE_REASON_LABELS: Record<DuplicateReason, string> = {
  SAME_URL: "the same link",
  SAME_CONTENT: "the same description",
};

/** The `details` of a 409 from `POST /api/v1/jobs`. */
export interface DuplicateDetails {
  existing_job_id: string;
  existing_title: string;
  reason: DuplicateReason;
}

/** Narrow an `ApiError.details` to the duplicate payload. */
export function isDuplicateDetails(value: unknown): value is DuplicateDetails {
  if (typeof value !== "object" || value === null) return false;
  const details = value as Record<string, unknown>;
  return (
    typeof details.existing_job_id === "string" &&
    typeof details.existing_title === "string" &&
    (details.reason === "SAME_URL" || details.reason === "SAME_CONTENT")
  );
}

/** Body of `POST /api/v1/jobs/archive`. Bounded by one page: the only way to
 * select rows is to see them. */
/** One band of the alignment distribution. */
export interface AlignmentBucket {
  floor: number;
  label: string;
  count: number;
}

/**
 * The shape of the filtered set, from `GET /api/v1/jobs/distribution`.
 *
 * Across everything the filters match, not the page — the figure exists so a
 * reader can reach a subset without walking ten pages of rows.
 *
 * `unscored` stands apart from the bands rather than joining the lowest one. A
 * job nobody matched has not scored badly, and counting it as "Little
 * alignment" would make the histogram claim something about jobs no one
 * measured.
 */
export interface AlignmentDistribution {
  buckets: AlignmentBucket[];
  unscored: number;
  total: number;
}

/** Body of `POST /api/v1/jobs/archive`. */
export interface BulkArchiveRequest {
  job_ids: string[];
}

/**
 * What happened to each id, rather than whether it all worked.
 *
 * Two lists because a screen has to name what it could not do. The call is not
 * atomic on purpose — reversing archives the user asked for, to punish an id
 * that was not theirs, would destroy work over a mismatch — so a partial result
 * is the ordinary outcome and not an error.
 *
 * `missing` covers both "no such job" and "not yours". Reporting them apart
 * would tell a caller which of another user's ids exist.
 */
export interface BulkArchiveResult {
  archived: string[];
  missing: string[];
}

/** Orderings the list offers. */
export type JobSort = "NEWEST" | "OLDEST" | "TITLE" | "COMPANY" | "BEST_ALIGNED";

export const JOB_SORT_LABELS: Record<JobSort, string> = {
  NEWEST: "Newest first",
  OLDEST: "Oldest first",
  TITLE: "Title A–Z",
  COMPANY: "Company A–Z",
  BEST_ALIGNED: "Best aligned first",
};

/**
 * Orderings that move scored jobs above unscored ones.
 *
 * A screen sorting by one of these has to say what happened to the rest: they
 * come last, and last in a ranking reads as worst unless the list separates
 * them and names the rule. Never a default — see `JobSort.BEST_ALIGNED` in
 * `application/jobs/queries.py` for why.
 */
export function sortsUnscoredLast(sort: JobSort): boolean {
  return sort === "BEST_ALIGNED";
}

/** Which side of the archive to show. */
export type ArchivedFilter = "ACTIVE" | "ARCHIVED" | "ALL";

/** Query parameters for `GET /api/v1/jobs`. */
/**
 * A named set of list filters.
 *
 * A view is a question, not a position in the answer, so `page` is never part
 * of one — reopening a saved view drops you at the start of it rather than on
 * page four of a list you have not seen.
 */
export interface SavedJobView {
  id: string;
  name: string;
  /** The stored query. A subset of `JobListQuery`, without `page`. */
  filters: SavedViewFilters;
  created_at: string;
  updated_at: string;
  /**
   * Whether this version of the app can still run the view.
   *
   * False when a stored filter no longer parses — an enum member that has been
   * removed, a number out of range, a key the API no longer has. The offending
   * keys are **kept** rather than dropped: silently removing one would return a
   * wider list than the name promises with nothing on screen admitting it.
   */
  is_readable: boolean;
  /** Which keys are responsible, so a screen can name them. */
  unreadable: string[];
}

export type SavedViewFilters = Omit<JobListQuery, "page">;

export interface SavedJobViewCreate {
  name: string;
  filters: SavedViewFilters;
}

export interface JobListQuery {
  search?: string;
  company?: string;
  work_mode?: WorkMode | "";
  employment_type?: EmploymentType | "";
  seniority?: Seniority | "";
  status?: JobStatus | "";
  archived?: ArchivedFilter;
  /**
   * An alignment band, as a closed range.
   *
   * Excludes unscored jobs rather than reading a missing score as zero — a band
   * is a question about jobs that were measured.
   */
  min_score?: number;
  max_score?: number;
  sort?: JobSort;
  page?: number;
  page_size?: number;
}

// --- job intelligence ---------------------------------------------------------

/** The nine requirement types from `docs/03-domain-model.md`. */
export type RequirementType =
  | "TECHNICAL_SKILL"
  | "EXPERIENCE"
  | "EDUCATION"
  | "LANGUAGE"
  | "DOMAIN_KNOWLEDGE"
  | "SOFT_SKILL"
  | "LOCATION"
  | "WORK_AUTHORIZATION"
  | "OTHER";

export const REQUIREMENT_TYPE_LABELS: Record<RequirementType, string> = {
  TECHNICAL_SKILL: "Technical skills",
  EXPERIENCE: "Experience",
  EDUCATION: "Education",
  LANGUAGE: "Languages",
  DOMAIN_KNOWLEDGE: "Domain knowledge",
  SOFT_SKILL: "Ways of working",
  LOCATION: "Location",
  WORK_AUTHORIZATION: "Work authorisation",
  OTHER: "Other",
};

/**
 * The order requirement groups are shown in.
 *
 * Not alphabetical and not the enum's own order. What can rule someone out
 * comes first — work authorisation and location are the things worth knowing
 * before reading any further — then what the role is built on, then the rest.
 */
export const REQUIREMENT_TYPE_ORDER: RequirementType[] = [
  "WORK_AUTHORIZATION",
  "LOCATION",
  "TECHNICAL_SKILL",
  "EXPERIENCE",
  "EDUCATION",
  "DOMAIN_KNOWLEDGE",
  "LANGUAGE",
  "SOFT_SKILL",
  "OTHER",
];

/**
 * How much the posting insists.
 *
 * `docs/05-ai-and-matching.md`: importance must preserve source meaning, and
 * "nice to have" must not become "required".
 */
export type RequirementImportance = "CORE" | "REQUIRED" | "PREFERRED" | "OPTIONAL" | "UNKNOWN";

export const IMPORTANCE_LABELS: Record<RequirementImportance, string> = {
  CORE: "Essential",
  REQUIRED: "Required",
  PREFERRED: "Preferred",
  OPTIONAL: "Optional",
  UNKNOWN: "Not stated",
};

/** Whether failing this would count against a candidate. */
export function isMandatory(importance: RequirementImportance): boolean {
  return importance === "CORE" || importance === "REQUIRED";
}

/** Whether the posting stated it, or the reader inferred it. */
export type RequirementExplicitness = "EXPLICIT" | "IMPLIED";

/** The initial families from `docs/05-ai-and-matching.md`, plus an escape. */
export type RoleFamily =
  | "BACKEND"
  | "FRONTEND"
  | "FULL_STACK"
  | "SOFTWARE"
  | "AI_ML"
  | "DATA_ENGINEERING"
  | "COMPUTER_VISION"
  | "DEVOPS"
  | "CYBERSECURITY"
  | "OTHER";

export const ROLE_FAMILY_LABELS: Record<RoleFamily, string> = {
  BACKEND: "Backend engineering",
  FRONTEND: "Frontend engineering",
  FULL_STACK: "Full stack engineering",
  SOFTWARE: "Software engineering",
  AI_ML: "AI / ML",
  DATA_ENGINEERING: "Data engineering",
  COMPUTER_VISION: "Computer vision",
  DEVOPS: "DevOps",
  CYBERSECURITY: "Cybersecurity",
  OTHER: "Something else",
};

/** Seniority a posting implies. The set named in `docs/05-ai-and-matching.md`. */
export type AnalyzedSeniority =
  "INTERN" | "ENTRY_LEVEL" | "JUNIOR" | "MID" | "SENIOR" | "STAFF_PLUS" | "UNKNOWN";

export const ANALYZED_SENIORITY_LABELS: Record<AnalyzedSeniority, string> = {
  INTERN: "Internship",
  ENTRY_LEVEL: "Entry level",
  JUNIOR: "Junior",
  MID: "Mid-level",
  SENIOR: "Senior",
  STAFF_PLUS: "Staff or above",
  UNKNOWN: "Not clear from the posting",
};

/** One thing the posting asks for. */
export interface JobRequirement {
  id: string;
  requirement_type: RequirementType;
  importance: RequirementImportance;
  explicitness: RequirementExplicitness;
  /** The posting's own words. Never rewritten, and always shown on request. */
  source_text: string;
  normalized_text: string;
  confidence: number;
  source_order: number;
  /** The canonical skill this resolved to, when one exists. */
  skill_id: string | null;
  skill_name: string | null;
  years_min: number | null;
}

/** One thing the role does. */
export interface JobResponsibility {
  id: string;
  text: string;
  source_text: string | null;
  confidence: number;
  source_order: number;
}

/** A versioned interpretation of a job. */
export interface JobAnalysis {
  id: string;
  job_id: string;
  version: number;
  summary: string | null;
  role_family: RoleFamily | null;
  secondary_role_family: RoleFamily | null;
  role_family_confidence: number | null;
  role_family_reasoning: string | null;
  seniority: AnalyzedSeniority;
  seniority_confidence: number | null;
  seniority_reasoning: string | null;
  domain: string | null;
  years_experience_min: number | null;
  years_experience_max: number | null;
  model: string;
  parse_prompt_version: string;
  analysis_prompt_version: string | null;
  /** What validation corrected or could not verify. Shown to the user. */
  warnings: string[];
  analyzed_at: string | null;
  created_at: string;
}

/** The state of the most recent analysis attempt. */
export interface AnalysisProcessingState {
  id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  step: "QUEUED" | "EXTRACTING" | "PARSING" | "ANALYZING" | "COMPLETED";
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  is_retriable: boolean;
}

/** Payload of `GET /api/v1/jobs/{id}/analysis`. */
export interface JobAnalysisView {
  job_id: string;
  job_status: JobStatus;
  analysis: JobAnalysis | null;
  requirements: JobRequirement[];
  responsibilities: JobResponsibility[];
  processing: AnalysisProcessingState | null;
  /** Whether the description has been edited since this analysis read it. */
  is_stale: boolean;
  available_versions: number[];
  /** Whether asking for an analysis right now would be accepted. */
  can_analyze: boolean;
}

/** The 202 body of `POST /api/v1/jobs/{id}/analysis`. */
export interface StartedAnalysis {
  job_id: string;
  processing_job_id: string;
  status: AnalysisProcessingState["status"];
}

// --- matching -----------------------------------------------------------------

/**
 * The verdict on one requirement.
 *
 * Three of these mean "no match" and must not be conflated. GAP is a real
 * absence. NO_EVIDENCE means we have nothing on file to judge with, and is
 * excluded from the score rather than counted as a failure. UNKNOWN means the
 * requirement cannot be checked automatically at all — never a gap, never a
 * blocker.
 */
export type MatchStatus =
  | "STRONG_MATCH"
  | "MATCH"
  | "PARTIAL_MATCH"
  | "TRANSFERABLE_MATCH"
  | "NO_EVIDENCE"
  | "GAP"
  | "BLOCKER"
  | "UNKNOWN";

export const MATCH_STATUS_LABELS: Record<MatchStatus, string> = {
  STRONG_MATCH: "Strong match",
  MATCH: "Match",
  PARTIAL_MATCH: "Partial match",
  TRANSFERABLE_MATCH: "Transferable",
  NO_EVIDENCE: "Nothing on file",
  GAP: "Gap",
  BLOCKER: "Blocker",
  UNKNOWN: "Check yourself",
};

/**
 * Semantic colour per status, from `docs/08-ui-ux.md`.
 *
 * Never used alone — every status also carries its label and an icon, because
 * the document is explicit that colour must not be the only signal.
 */
export const MATCH_STATUS_TONE: Record<
  MatchStatus,
  "strong" | "ok" | "transfer" | "gap" | "blocked" | "neutral"
> = {
  STRONG_MATCH: "strong",
  MATCH: "strong",
  PARTIAL_MATCH: "ok",
  TRANSFERABLE_MATCH: "transfer",
  NO_EVIDENCE: "neutral",
  GAP: "gap",
  BLOCKER: "blocked",
  UNKNOWN: "neutral",
};

export function isPositiveMatch(status: MatchStatus): boolean {
  return (
    status === "STRONG_MATCH" ||
    status === "MATCH" ||
    status === "PARTIAL_MATCH" ||
    status === "TRANSFERABLE_MATCH"
  );
}

export type MatchCategory =
  "TECHNICAL" | "EXPERIENCE" | "PROJECTS" | "EDUCATION" | "DOMAIN" | "PREFERRED" | "OTHER";

export const MATCH_CATEGORY_LABELS: Record<MatchCategory, string> = {
  TECHNICAL: "Technical skills",
  EXPERIENCE: "Experience",
  PROJECTS: "Projects",
  EDUCATION: "Education",
  DOMAIN: "Domain knowledge",
  PREFERRED: "Preferred extras",
  OTHER: "Other",
};

export type MatchRecommendation =
  "STRONG_APPLY" | "APPLY" | "CONSIDER" | "LOW_PRIORITY" | "PROBABLY_SKIP";

export const RECOMMENDATION_LABELS: Record<MatchRecommendation, string> = {
  STRONG_APPLY: "Strong apply",
  APPLY: "Apply",
  CONSIDER: "Worth considering",
  LOW_PRIORITY: "Low priority",
  PROBABLY_SKIP: "Probably skip",
};

/** Which part of the career profile a piece of evidence came from. */
export type EvidenceType = "SKILL" | "EXPERIENCE" | "ACHIEVEMENT" | "PROJECT" | "EDUCATION";

export const EVIDENCE_TYPE_LABELS: Record<EvidenceType, string> = {
  SKILL: "Skill",
  EXPERIENCE: "Role",
  ACHIEVEMENT: "Achievement",
  PROJECT: "Project",
  EDUCATION: "Education",
};

/** One career fact behind a verdict. */
export interface MatchEvidence {
  id: string;
  evidence_type: EvidenceType;
  entity_id: string;
  label: string;
  detail: string | null;
  verification_status: string;
  relevance: number;
}

/** The verdict on one requirement, with the evidence behind it. */
export interface MatchItem {
  id: string;
  requirement_id: string;
  status: MatchStatus;
  category: MatchCategory;
  score: number;
  weight: number;
  confidence: number;
  explanation: string;
  is_blocker: boolean;
  source_order: number;
  evidence: MatchEvidence[];
  /**
   * The requirement this verdict was made against, in the posting's words.
   *
   * Sent with the item rather than joined client-side, because the analysis
   * this client can fetch is the job's latest and this verdict was scored
   * against a specific version of it. On a stale match those differ, and a
   * quote that is meant to be checkable would be checkable against the wrong
   * text.
   *
   * `importance` comes from here and the verdict from the item, which is what
   * lets the two be laid out on one field. Null only for a payload built
   * without the join.
   */
  requirement: JobRequirement | null;
}

export interface CategoryScore {
  category: string;
  score: number | null;
  weight: number;
  item_count: number;
  scored_count: number;
}

/** A scored match. */
export interface JobMatch {
  id: string;
  job_id: string;
  version: number;
  /** Null when nothing could be scored. Zero would be a claim about the
   * candidate; null is a claim about our information. */
  overall_score: number | null;
  alignment_label: string | null;
  score_cap: number | null;
  score_cap_reason: string | null;
  recommendation: MatchRecommendation;
  recommendation_reasons: string[];
  confidence: number;
  summary: string | null;
  category_scores: Record<string, CategoryScore>;
  status_counts: Record<string, number>;
  has_blockers: boolean;
  scored_requirements: number;
  total_requirements: number;
  warnings: string[];
  analysis_version: number;
  engine_version: string;
  computed_at: string | null;
  created_at: string;
}

/** Payload of `GET /api/v1/jobs/{id}/match`. */
export interface JobMatchView {
  job_id: string;
  match: JobMatch | null;
  items: MatchItem[];
  is_stale: boolean;
  stale_reasons: string[];
  available_versions: number[];
  can_match: boolean;
  blocking_reason: string | null;
  /**
   * What the user said they want, against what this posting says.
   *
   * Beside the match, never inside it. Alignment is about evidence — whether
   * the profile answers what the posting asked for — and a job in the wrong
   * city does not fit your skills any less. Every dimension is always present,
   * including the ones nobody set and the ones the posting is silent about,
   * because a short list of satisfied preferences reads as a clean bill of
   * health when it is really a list of things nobody checked.
   */
  preference_fit: PreferenceFit[];
}
