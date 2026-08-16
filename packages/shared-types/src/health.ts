/** Contracts for the API health endpoints. */

export type Environment = "local" | "test" | "staging" | "production";

/** Payload of `GET /api/v1/health`. */
export interface HealthPayload {
  status: "ok";
  service: string;
  version: string;
  environment: Environment;
}

export type DependencyStatus = "ok" | "unavailable";

export interface DependencyReport {
  status: DependencyStatus;
  detail: string | null;
}

/** Payload of `GET /api/v1/health/ready` when every dependency responds. */
export interface ReadinessPayload {
  status: "ready" | "degraded";
  dependencies: Record<string, DependencyReport>;
}

/** Paths owned by the API, kept in one place so callers do not hard-code them. */
export const API_ROUTES = {
  health: "/api/v1/health",
  readiness: "/api/v1/health/ready",
  currentUser: "/api/v1/users/me",
  careerProfile: "/api/v1/career/profile",
  careerPreferences: "/api/v1/career/preferences",
  careerTargetRoles: "/api/v1/career/target-roles",
  careerSkills: "/api/v1/career/skills",
  careerExperiences: "/api/v1/career/experiences",
  careerProjects: "/api/v1/career/projects",
  careerEducation: "/api/v1/career/education",
  careerCertifications: "/api/v1/career/certifications",
  skillCandidates: "/api/v1/skill-candidates",
  resumeImport: "/api/v1/resumes/import",
  resumeImports: "/api/v1/resumes/imports",
  resumeSupportedFormats: "/api/v1/resumes/supported-formats",
  processingJobs: "/api/v1/processing-jobs",
  jobs: "/api/v1/jobs",
  jobCompanies: "/api/v1/jobs/companies",
  resumes: "/api/v1/resumes",
  resumeVersions: "/api/v1/resume-versions",
  resumeStrategies: "/api/v1/resume-strategies",
  resumeSuggestions: "/api/v1/resume-suggestions",
  applications: "/api/v1/applications",
  dashboard: "/api/v1/dashboard",
  insightsOverview: "/api/v1/insights/overview",
  insightsSkillDemand: "/api/v1/insights/skills/demand",
  insightsSkillGaps: "/api/v1/insights/skills/gaps",
  insightsRoles: "/api/v1/insights/roles",
  insightsFunnel: "/api/v1/insights/applications/funnel",
  insightsResumes: "/api/v1/insights/resumes",
} as const;
