import type { RequirementImportance, RoleFamily } from "./jobs";

/**
 * How much of a gap a skill is, from `docs/07`.
 *
 * Four states rather than a boolean, because "on the profile" is not the same
 * as "evidenced": a skill an import inferred is a claim, a skill the user
 * confirmed but attached to nothing is a claim they believe, and a skill
 * attached to real work is a record.
 */
export type GapState = "STRONG_GAP" | "PARTIAL_GAP" | "WEAK_EVIDENCE" | "NO_GAP";

/** What each state means, in the user's terms rather than the enum's. */
export const GAP_STATE_LABELS: Record<GapState, string> = {
  STRONG_GAP: "Not on your profile",
  PARTIAL_GAP: "Not confirmed by you",
  WEAK_EVIDENCE: "Listed, not demonstrated",
  NO_GAP: "Covered",
};

/** The sentence under each, saying what would close it. */
export const GAP_STATE_HINTS: Record<GapState, string> = {
  STRONG_GAP: "Nothing in your profile mentions it.",
  PARTIAL_GAP: "It came from an import and you have not confirmed it.",
  WEAK_EVIDENCE: "It is on your profile but not attached to any role or project.",
  NO_GAP: "Confirmed, and demonstrated in your work.",
};

export interface SkillDemandEntry {
  /** Canonical id where the catalogue knows the skill, normalised name where
      it does not. Stable enough to key a list on. */
  key: string;
  skill_id: string | null;
  name: string;
  /** Whether this resolved to the shared skill catalogue. */
  catalogued: boolean;
  /** How many of the user's analysed jobs asked for it. */
  jobs: number;
  /** That, as a percentage of the same set. */
  share: number;
  importance: Partial<Record<RequirementImportance, number>>;
  role_families: Record<string, number>;
  state: GapState;
  held: boolean;
}

/** Everything on this screen carries the sample it was counted over. */
interface Sampled {
  analysed_jobs: number;
  minimum_jobs: number;
  above_threshold: boolean;
}

export interface SkillDemandReport extends Sampled {
  skills: SkillDemandEntry[];
}

export interface SkillGapReport extends Sampled {
  gaps: SkillDemandEntry[];
}

export interface InsightsOverview extends Sampled {
  skills_tracked: number;
  gaps_found: number;
  top_skills: SkillDemandEntry[];
  top_gaps: SkillDemandEntry[];
}

/** One role family, and how the user's jobs in it have gone. */
export interface RoleInsight {
  role_family: RoleFamily;
  jobs: number;
  matched: number;
  /** Null below the threshold, and null when nothing in the family scored.
      Never zero — that would be a claim about fit, not about data. */
  average_alignment: number | null;
  applications: number;
}

export interface RoleReport {
  minimum_jobs: number;
  roles: RoleInsight[];
}

export interface FunnelStage {
  key: string;
  label: string;
  /** Applications that got *at least* this far, read from their history —
      not their current status, which would report every rejection as never
      having applied. */
  reached: number;
}

export interface FunnelReport {
  applications: number;
  minimum_applications: number;
  /** Whether the client may divide these counts. Decided server-side so the
      threshold lives in one place. */
  rates_are_meaningful: boolean;
  stages: FunnelStage[];
}

export interface ResumeInsight {
  resume_version_id: string;
  label: string;
  sent: number;
  reached_interview: number;
  offers: number;
}

export interface ResumePerformanceReport {
  minimum_applications: number;
  rates_are_meaningful: boolean;
  versions: ResumeInsight[];
}
