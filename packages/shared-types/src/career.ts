import { API_ROUTES } from "./health";
import type { RoleFamily, WorkMode } from "./jobs";

/** Contracts for the career profile API. */

/** A labelled external link on the profile. */
export interface ProfileLink {
  label: string;
  url: string;
}

/** Payload of `GET` and `PATCH /api/v1/career/profile`. */
export interface CareerProfile {
  id: string;
  headline: string | null;
  professional_summary: string | null;
  years_of_experience: number | null;
  current_location: string | null;
  links: ProfileLink[];
  created_at: string;
  updated_at: string;
}

/**
 * Body of `PATCH /api/v1/career/profile`.
 *
 * Every field is optional, and the distinction matters: omitting a key leaves
 * the stored value alone, while sending `null` clears it. Callers must not
 * send the whole object back on every save, or an unrelated field edited in
 * another tab gets overwritten.
 */
export interface CareerProfileUpdate {
  headline?: string | null;
  professional_summary?: string | null;
  years_of_experience?: number | null;
  current_location?: string | null;
  links?: ProfileLink[];
}

/** Verification states from `docs/03-domain-model.md`. */
export type VerificationStatus =
  "UNVERIFIED" | "AI_INFERRED" | "USER_CONFIRMED" | "EVIDENCE_BACKED";

/** Seniority levels a user can target. Mirrors the backend enum. */
export type Seniority =
  "INTERN" | "JUNIOR" | "MID" | "SENIOR" | "STAFF" | "PRINCIPAL" | "LEAD" | "MANAGER";

export const SENIORITY_LABELS: Record<Seniority, string> = {
  INTERN: "Intern",
  JUNIOR: "Junior",
  MID: "Mid",
  SENIOR: "Senior",
  STAFF: "Staff",
  PRINCIPAL: "Principal",
  LEAD: "Lead",
  MANAGER: "Manager",
};

/** A role the user is aiming for. */
export interface TargetRole {
  id: string;
  title: string;
  role_family: string | null;
  desired_seniority: Seniority | null;
  priority: number;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

/** Body of `POST /api/v1/career/target-roles`. */
export interface TargetRoleCreate {
  title: string;
  role_family?: string | null;
  desired_seniority?: Seniority | null;
  priority?: number;
  is_active?: boolean;
  notes?: string | null;
}

/** Body of `PATCH /api/v1/career/target-roles/{id}`. Omitted keys are untouched. */
export type TargetRoleUpdate = Partial<TargetRoleCreate>;

// --- skills ------------------------------------------------------------------

export type SkillCategory =
  | "LANGUAGE"
  | "FRAMEWORK"
  | "DATABASE"
  | "TOOL"
  | "PLATFORM"
  | "PRACTICE"
  | "DOMAIN"
  | "SOFT_SKILL"
  | "OTHER";

export const SKILL_CATEGORY_LABELS: Record<SkillCategory, string> = {
  LANGUAGE: "Language",
  FRAMEWORK: "Framework",
  DATABASE: "Database",
  TOOL: "Tool",
  PLATFORM: "Platform",
  PRACTICE: "Practice",
  DOMAIN: "Domain",
  SOFT_SKILL: "Soft skill",
  OTHER: "Other",
};

export type Proficiency = "BEGINNER" | "INTERMEDIATE" | "ADVANCED" | "EXPERT";

export const PROFICIENCY_LABELS: Record<Proficiency, string> = {
  BEGINNER: "Beginner",
  INTERMEDIATE: "Intermediate",
  ADVANCED: "Advanced",
  EXPERT: "Expert",
};

export interface UserSkill {
  id: string;
  skill_id: string;
  name: string;
  category: SkillCategory;
  proficiency: Proficiency | null;
  years_of_experience: number | null;
  last_used_year: number | null;
  verification_status: VerificationStatus;
  source: string;
  notes: string | null;
}

export interface UserSkillCreate {
  name: string;
  category?: SkillCategory;
  proficiency?: Proficiency | null;
  years_of_experience?: number | null;
  last_used_year?: number | null;
  notes?: string | null;
}

/** Where a piece of evidence for a skill came from. */
export type EvidenceSource =
  "MANUAL" | "EDUCATION" | "CERTIFICATION" | "RESUME" | "EXPERIENCE" | "PROJECT";

export interface SkillEvidence {
  id: string;
  source: EvidenceSource;
  note: string | null;
}

export interface SkillEvidenceCreate {
  note: string;
}

/**
 * Stated reasons for one skill. Nested under the skill because evidence has no
 * meaning apart from it, and because scoping the read by both ids is what stops
 * one user reaching another's.
 */
export function careerSkillEvidenceRoute(skillId: string): string {
  return `${API_ROUTES.careerSkills}/${skillId}/evidence`;
}

// --- experience --------------------------------------------------------------

export type EmploymentType =
  "FULL_TIME" | "PART_TIME" | "CONTRACT" | "FREELANCE" | "INTERNSHIP" | "VOLUNTEER";

export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  FULL_TIME: "Full-time",
  PART_TIME: "Part-time",
  CONTRACT: "Contract",
  FREELANCE: "Freelance",
  INTERNSHIP: "Internship",
  VOLUNTEER: "Volunteer",
};

/** A bullet-level fact belonging to a role. */
export interface ExperienceAchievement {
  id: string;
  text: string;
  display_order: number;
  verification_status: VerificationStatus;
}

export interface Experience {
  id: string;
  company: string;
  title: string;
  employment_type: EmploymentType | null;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string | null;
  verification_status: VerificationStatus;
  /** Nested rather than fetched separately: an achievement is never useful
   * without its role. Resume approval can write these. */
  achievements: ExperienceAchievement[];
}

export interface ExperienceCreate {
  company: string;
  title: string;
  employment_type?: EmploymentType | null;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  is_current?: boolean;
  description?: string | null;
}

// --- projects ----------------------------------------------------------------

export type ProjectType =
  "PERSONAL" | "ACADEMIC" | "PROFESSIONAL" | "OPEN_SOURCE" | "FREELANCE" | "RESEARCH";

export const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  PERSONAL: "Personal",
  ACADEMIC: "Academic",
  PROFESSIONAL: "Professional",
  OPEN_SOURCE: "Open source",
  FREELANCE: "Freelance",
  RESEARCH: "Research",
};

export type ProjectStatus = "IN_PROGRESS" | "COMPLETED" | "MAINTAINED" | "ARCHIVED";

export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  IN_PROGRESS: "In progress",
  COMPLETED: "Completed",
  MAINTAINED: "Maintained",
  ARCHIVED: "Archived",
};

export interface Project {
  id: string;
  name: string;
  project_type: ProjectType | null;
  status: ProjectStatus | null;
  summary: string | null;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  repository_url: string | null;
  demo_url: string | null;
  documentation_url: string | null;
  verification_status: VerificationStatus;
  /** Canonical names of the technologies this project used. */
  skills: string[];
}

export interface ProjectCreate {
  name: string;
  project_type?: ProjectType | null;
  status?: ProjectStatus | null;
  summary?: string | null;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  repository_url?: string | null;
  demo_url?: string | null;
  documentation_url?: string | null;
}

// --- education ---------------------------------------------------------------

export interface Education {
  id: string;
  institution: string;
  degree: string | null;
  field_of_study: string | null;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  grade: string | null;
  description: string | null;
  verification_status: VerificationStatus;
}

export interface EducationCreate {
  institution: string;
  degree?: string | null;
  field_of_study?: string | null;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  is_current?: boolean;
  grade?: string | null;
  description?: string | null;
}

// --- certifications -----------------------------------------------------------

export interface Certification {
  id: string;
  name: string;
  issuer: string;
  /** ISO date, or null when the user did not record one. */
  issued_on: string | null;
  /**
   * ISO date, or null meaning **it does not expire** — never "expiry unknown".
   * The matcher reads it that way too: deciding a credential had lapsed on no
   * evidence would be the platform inventing a shortfall.
   */
  expires_on: string | null;
  credential_id: string | null;
  credential_url: string | null;
  description: string | null;
  verification_status: VerificationStatus;
}

export interface CertificationCreate {
  name: string;
  issuer: string;
  issued_on?: string | null;
  expires_on?: string | null;
  credential_id?: string | null;
  credential_url?: string | null;
  description?: string | null;
}

// --- skill review queue -------------------------------------------------------

export type CandidateStatus = "PENDING" | "ACCEPTED" | "REJECTED";

/**
 * A technology a posting named that the canonical catalogue could not resolve.
 *
 * DEV-062. Job postings are not allowed to write to the shared catalogue — the
 * name came from a model reading someone else's prose, and that path would fill
 * a shared table with "Rust (advantageous)". So an unresolved name queues here
 * and a person decides.
 */
export interface SkillCandidate {
  id: string;
  normalized_name: string;
  display_name: string;
  /** How many stored requirements use this name. The queue is ordered by it. */
  occurrences: number;
  status: CandidateStatus;
  resolved_skill_id: string | null;
  note: string | null;
  /**
   * The posting's own sentence. Load-bearing rather than decorative: `CAN`
   * arrives as a three-letter string that is also an ordinary English word, and
   * only *"communication protocols such as UART, SPI, I2C, TCP/IP, or CAN"*
   * identifies it as the CAN bus.
   */
  example_source_text: string | null;
  example_job_title: string | null;
}

export interface AcceptAsAliasRequest {
  skill_id: string;
  note?: string | null;
}

export interface AcceptAsNewSkillRequest {
  category: SkillCategory;
  /** Lets the reviewer correct the posting's spelling. The posting's wording is
   * kept as an alias either way, so the requirement still resolves. */
  canonical_name?: string | null;
  note?: string | null;
}

export interface RejectCandidateRequest {
  note?: string | null;
}

// --- preferences --------------------------------------------------------------

/**
 * What the user will and will not take.
 *
 * Every list is empty by default and empty means **no constraint**, never a
 * constraint of zero. A user who has not opened Settings has not declined
 * anything, and every consumer has to read absence that way.
 */
export interface CareerPreferences {
  id: string;
  work_modes: WorkMode[];
  employment_types: EmploymentType[];
  locations: string[];
  /** Three-valued: yes, no, and not answered. `null` must not narrow anything. */
  open_to_relocation: boolean | null;
  salary_min: number | null;
  salary_currency: string | null;
  excluded_role_families: RoleFamily[];
  created_at: string;
  updated_at: string;
}

/** Body of `PATCH /api/v1/career/preferences`. Omitted fields are left alone. */
export interface CareerPreferencesUpdate {
  work_modes?: WorkMode[];
  employment_types?: EmploymentType[];
  locations?: string[];
  open_to_relocation?: boolean | null;
  salary_min?: number | null;
  salary_currency?: string | null;
  excluded_role_families?: RoleFamily[];
}

/**
 * How one stated preference stands against one posting.
 *
 * Three of the six are ways of saying "no answer", and they are the point.
 * Reporting a posting that states nothing as matching a remote-only preference
 * is the quiet lie DEV-035 is about.
 */
export type FitVerdict =
  "MATCHES" | "CONFLICTS" | "UNCONFIRMED" | "NOT_STATED" | "NO_PREFERENCE" | "NOT_COMPARED";

export const FIT_VERDICT_LABELS: Record<FitVerdict, string> = {
  MATCHES: "Matches",
  CONFLICTS: "Against your preference",
  UNCONFIRMED: "Could not confirm",
  NOT_STATED: "The posting does not say",
  NO_PREFERENCE: "You have not said",
  NOT_COMPARED: "Not compared",
};

export interface PreferenceFit {
  dimension: string;
  verdict: FitVerdict;
  detail: string;
}

export const PREFERENCE_DIMENSION_LABELS: Record<string, string> = {
  work_mode: "Work mode",
  employment_type: "Employment type",
  location: "Location",
  role_family: "Role type",
  salary: "Salary",
};
