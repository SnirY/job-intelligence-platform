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
