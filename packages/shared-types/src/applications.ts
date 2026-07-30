/** Contracts for the application tracker. */

/**
 * The lifecycle from `docs/07-applications-and-career-intelligence.md`.
 *
 * One sequence rather than a stage plus an outcome: a rejection *is* where the
 * process got to, and splitting them would mean every "where is this" question
 * had to read two fields and know which wins.
 */
export type ApplicationStatus =
  | "SAVED"
  | "INTERESTED"
  | "ANALYZING"
  | "PREPARING"
  | "READY_TO_APPLY"
  | "APPLIED"
  | "HR_SCREEN"
  | "TECHNICAL_INTERVIEW"
  | "FINAL_INTERVIEW"
  | "OFFER"
  | "REJECTED"
  | "WITHDRAWN"
  | "GHOSTED"
  | "ARCHIVED";

export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  SAVED: "Saved",
  INTERESTED: "Interested",
  ANALYZING: "Analysing",
  PREPARING: "Preparing",
  READY_TO_APPLY: "Ready to apply",
  APPLIED: "Applied",
  HR_SCREEN: "HR screen",
  TECHNICAL_INTERVIEW: "Technical interview",
  FINAL_INTERVIEW: "Final interview",
  OFFER: "Offer",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
  GHOSTED: "No reply",
  ARCHIVED: "Archived",
};

/**
 * The board's columns, in order.
 *
 * Endings are deliberately absent. A Kanban with a Rejected column turns the
 * screen into a monument to rejection — `docs/08-ui-ux.md` asks for a board of
 * live work, and an ended application belongs in the table view.
 */
export const BOARD_COLUMNS: ApplicationStatus[] = [
  "SAVED",
  "INTERESTED",
  "PREPARING",
  "READY_TO_APPLY",
  "APPLIED",
  "HR_SCREEN",
  "TECHNICAL_INTERVIEW",
  "FINAL_INTERVIEW",
  "OFFER",
];

export const TERMINAL_STATUSES: ApplicationStatus[] = [
  "REJECTED",
  "WITHDRAWN",
  "GHOSTED",
  "ARCHIVED",
];

export function isTerminal(status: ApplicationStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/** Where it was submitted. A referral and a job board are not the same channel. */
export type ApplicationSource =
  "COMPANY_WEBSITE" | "JOB_BOARD" | "LINKEDIN" | "REFERRAL" | "RECRUITER" | "EMAIL" | "OTHER";

export const APPLICATION_SOURCE_LABELS: Record<ApplicationSource, string> = {
  COMPANY_WEBSITE: "Company website",
  JOB_BOARD: "Job board",
  LINKEDIN: "LinkedIn",
  REFERRAL: "Referral",
  RECRUITER: "Recruiter",
  EMAIL: "Email",
  OTHER: "Other",
};

export type ApplicationEventType =
  | "CREATED"
  | "STATUS_CHANGED"
  | "RESUME_ATTACHED"
  | "SUBMITTED"
  | "NOTE_ADDED"
  | "FEEDBACK_RECORDED";

export interface Application {
  id: string;
  job_id: string;
  status: ApplicationStatus;
  resume_version_id: string | null;
  applied_at: string | null;
  source: ApplicationSource | null;
  notes: string | null;
  /** What the employer actually said. Never inferred — see `docs/07`. */
  rejection_feedback: string | null;
  created_at: string;
  updated_at: string;

  job_title: string;
  company: string | null;

  /**
   * Served rather than derived in the browser.
   *
   * The lifecycle table lives in the domain layer; a second copy in TypeScript
   * would be two rules that have to agree, and the one that drifts is the one
   * the user sees.
   */
  allowed_transitions: ApplicationStatus[];

  /** Days since the last status change. Null until it has moved once. */
  days_in_stage: number | null;
}

export interface ApplicationEvent {
  id: string;
  event_type: ApplicationEventType;
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus | null;
  occurred_at: string;
  summary: string;
  detail: string | null;
}
