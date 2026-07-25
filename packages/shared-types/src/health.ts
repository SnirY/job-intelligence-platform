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
} as const;
