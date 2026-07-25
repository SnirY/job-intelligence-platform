import { isErrorResponse, type ApiErrorBody, type DataResponse } from "@jip/shared-types";

/**
 * Base URL of the backend API.
 *
 * Read from NEXT_PUBLIC_API_BASE_URL. This is a public value: it is inlined
 * into the browser bundle, so nothing secret may ever be passed this way.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** An error the API reported using the documented error envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

/** An error that prevented a response from being interpreted at all. */
export class ApiTransportError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ApiTransportError";
  }
}

/**
 * Call the API and unwrap the `data` envelope.
 *
 * Failures are surfaced as typed errors rather than a null result, so callers
 * cannot mistake "the request failed" for "the resource is empty".
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (cause) {
    throw new ApiTransportError(`Could not reach the API at ${API_BASE_URL}`, { cause });
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (cause) {
    throw new ApiTransportError(`The API returned a non-JSON response (HTTP ${response.status})`, {
      cause,
    });
  }

  if (isErrorResponse(payload)) {
    throw new ApiError(response.status, payload.error);
  }

  if (!response.ok) {
    throw new ApiTransportError(`The API returned HTTP ${response.status} without an error body`);
  }

  return (payload as DataResponse<T>).data;
}
