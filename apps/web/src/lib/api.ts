import {
  isErrorResponse,
  type ApiErrorBody,
  type CollectionResponse,
  type DataResponse,
} from "@jip/shared-types";

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

  /** True when the request failed because the caller is not authenticated. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
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
 * Supplies the bearer token for a request.
 *
 * Clerk session tokens are short-lived and the SDK refreshes them, so this is
 * called per request rather than resolved once — a token captured at mount
 * starts returning 401 well before the page is closed.
 */
export type TokenProvider = () => Promise<string | null>;

export interface ApiFetchOptions extends RequestInit {
  getToken?: TokenProvider;
}

/**
 * Call the API and unwrap the `data` envelope.
 *
 * Failures are surfaced as typed errors rather than a null result, so callers
 * cannot mistake "the request failed" for "the resource is empty".
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const payload = await apiFetchEnvelope(path, options);
  // 204 carries no body by definition, so parsing one would always throw.
  // DELETE endpoints answer this way; treating it as a transport failure would
  // report a successful delete as an error.
  if (payload === undefined) {
    return undefined as T;
  }
  return (payload as DataResponse<T>).data;
}

/**
 * Call the API and return a paginated collection envelope whole.
 *
 * Separate from `apiFetch` because a paginated list needs its `meta` — the
 * counts a pager is built from. Unwrapping to `data` like the single-resource
 * helper does would throw them away.
 */
export async function apiFetchPage<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<CollectionResponse<T>> {
  return (await apiFetchEnvelope(path, options)) as CollectionResponse<T>;
}

/** Shared transport for both helpers: everything except the unwrapping. */
async function apiFetchEnvelope(path: string, options: ApiFetchOptions): Promise<unknown> {
  const { getToken, headers, ...init } = options;

  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (getToken) {
    const token = await getToken();
    if (token) {
      requestHeaders.Authorization = `Bearer ${token}`;
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: requestHeaders });
  } catch (cause) {
    throw new ApiTransportError(`Could not reach the API at ${API_BASE_URL}`, { cause });
  }

  if (response.status === 204) {
    return undefined;
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

  return payload;
}
