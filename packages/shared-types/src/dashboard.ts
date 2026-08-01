import type { ApplicationStatus } from "./applications";

/**
 * The rule that produced a suggested action.
 *
 * Named for the situation rather than the button, so the wording lives in the
 * frontend and the backend stays a statement about the data.
 */
export type NextActionKind =
  | "BUILD_PROFILE"
  | "ANALYSE_JOB"
  | "RETRY_ANALYSIS"
  | "MATCH_JOB"
  | "REFRESH_MATCH"
  | "PREPARE_APPLICATION"
  | "FOLLOW_UP";

/**
 * What each action asks the user to do, in their words.
 *
 * A `Record` rather than a lookup with a fallback, so adding a kind to the API
 * without a label here fails to compile instead of rendering a raw enum name.
 */
export const NEXT_ACTION_LABELS: Record<NextActionKind, string> = {
  BUILD_PROFILE: "Add your experience",
  ANALYSE_JOB: "Read this posting",
  RETRY_ANALYSIS: "Try reading it again",
  MATCH_JOB: "Compare it to your profile",
  REFRESH_MATCH: "Work the match out again",
  PREPARE_APPLICATION: "Start an application",
  FOLLOW_UP: "Follow this one up",
};

export interface DashboardState {
  jobs_saved: number;
  jobs_analysed: number;
  jobs_matched: number;
  applications_live: number;
  profile_skills: number;
}

export interface PipelineStage {
  status: ApplicationStatus;
  count: number;
  /** Preparation rather than a real outcome. The funnel divides here. */
  before_applying: boolean;
}

export interface DashboardOpportunity {
  job_id: string;
  title: string;
  company: string | null;
  /** Null when nothing could be scored — never zero, which is a verdict. */
  score: number | null;
  alignment_label: string | null;
  is_stale: boolean;
  has_application: boolean;
}

export interface NextAction {
  kind: NextActionKind;
  subject: string;
  /** The evidence. Checkable against the screen this points at. */
  reason: string;
  job_id: string | null;
  application_id: string | null;
}

export interface ActivityEntry {
  at: string;
  kind: string;
  subject: string;
  job_id: string | null;
}

export interface SkillGap {
  skill_id: string;
  name: string;
  /** How many of the user's own saved jobs ask for it. */
  asked_by_jobs: number;
}

export interface Dashboard {
  state: DashboardState;
  pipeline: PipelineStage[];
  opportunities: DashboardOpportunity[];
  actions: NextAction[];
  activity: ActivityEntry[];
  skill_gaps: SkillGap[];
}

/** Where an action takes the user. Every action must lead somewhere real. */
export function actionHref(action: NextAction): string {
  if (action.kind === "BUILD_PROFILE") return "/career-profile";
  if (action.job_id) return `/jobs/${action.job_id}`;
  return "/applications";
}
