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
