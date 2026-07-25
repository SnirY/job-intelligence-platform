/**
 * Response envelopes from `docs/10-api-contracts.md`.
 *
 * These mirror the Pydantic models in `apps/api/src/jip_api/core/responses.py`.
 * They are hand-written for now; once the API surface grows beyond health
 * checks, generating them from the FastAPI OpenAPI document will be cheaper
 * than keeping two definitions in step.
 */

/** Single-resource success envelope. */
export interface DataResponse<T> {
  data: T;
}

/** Collection pagination metadata. */
export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

/** Collection success envelope. */
export interface CollectionResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

/** Machine-readable error description. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: unknown;
  request_id: string | null;
}

/** Error envelope. */
export interface ErrorResponse {
  error: ApiErrorBody;
}

/** Narrow an unknown API payload to the error envelope. */
export function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const { error } = value as { error: unknown };
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}
