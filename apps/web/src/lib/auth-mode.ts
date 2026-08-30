/**
 * Which authentication path this build runs.
 *
 * Mirrors the API's `JIP_AUTH_PROVIDER`: `local` verifies a token against a
 * shared secret, anything else goes to Clerk. The two must agree — a frontend
 * minting local tokens against an API expecting Clerk produces a working
 * sign-in followed by 401 on every request, which reads like a broken product
 * rather than a misconfiguration.
 *
 * `NEXT_PUBLIC_` because the browser decides which sign-in to render, so the
 * value is inlined into the bundle. It names a mode and carries no secret; the
 * secret it implies the existence of lives in `AUTH_LOCAL_SECRET`, which is
 * read only on the server.
 */
export const isLocalAuth = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "local";

/** Cookie holding the local session token. */
export const LOCAL_SESSION_COOKIE = "jip_local_session";
