import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * HS256 minting and verification for the local authentication mode.
 *
 * **Server only.** It reads `AUTH_LOCAL_SECRET`, which must never reach the
 * browser bundle — importing this from a client component is a mistake the
 * `node:crypto` import makes fail loudly rather than silently.
 *
 * Written against `node:crypto` rather than a JWT library on purpose. The
 * format needed here is one algorithm and four claims, the whole implementation
 * is visible on this page, and a demo convenience is a poor reason to add a
 * dependency to a project that keeps them few.
 *
 * The token this produces is the one
 * `apps/api/src/jip_api/infrastructure/auth/local.py` verifies. Both pin HS256
 * and both require `sub` and `exp`; a change to either side needs the same
 * change on the other.
 */

const ALGORITHM_HEADER = { alg: "HS256", typ: "JWT" } as const;

export const DEFAULT_SUBJECT = "local-demo-user";

/** Matches `MINIMUM_SECRET_LENGTH` in the API's local verifier. */
const MINIMUM_SECRET_LENGTH = 32;

function base64url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function fromBase64url(input: string): Buffer {
  return Buffer.from(input.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

function sign(payload: string, secret: string): string {
  return base64url(createHmac("sha256", secret).update(payload).digest());
}

/**
 * The configured secret, or `null` when local mode is not usable.
 *
 * Returns rather than throws: the caller renders an explanation, which is more
 * use to someone setting this up than a stack trace.
 */
export function localSecret(): string | null {
  const secret = process.env.AUTH_LOCAL_SECRET;
  if (!secret || secret.length < MINIMUM_SECRET_LENGTH) {
    return null;
  }
  return secret;
}

export interface LocalTokenClaims {
  sub: string;
  email?: string;
  name?: string;
}

/** Mint a token the API's local verifier will accept. */
export function mintLocalToken(
  secret: string,
  claims: LocalTokenClaims,
  ttlSeconds = 86_400,
): string {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    ...claims,
    iat: now,
    exp: now + ttlSeconds,
  };

  const encoded = `${base64url(JSON.stringify(ALGORITHM_HEADER))}.${base64url(
    JSON.stringify(payload),
  )}`;

  return `${encoded}.${sign(encoded, secret)}`;
}

/**
 * Verify a token and return its subject, or `null`.
 *
 * Checks the signature and the expiry — the same two things that decide it at
 * the API. Without the signature check the gate would pass for any cookie a
 * browser happened to hold, and the page would render before the first request
 * came back 401.
 */
export function verifyLocalToken(secret: string, token: string): string | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  const [header, payload, signature] = parts as [string, string, string];

  const expected = sign(`${header}.${payload}`, secret);
  const provided = fromBase64url(signature);
  const computed = fromBase64url(expected);
  if (provided.length !== computed.length || !timingSafeEqual(provided, computed)) {
    return null;
  }

  try {
    const claims: unknown = JSON.parse(fromBase64url(payload).toString("utf8"));
    if (typeof claims !== "object" || claims === null) return null;

    const { sub, exp } = claims as { sub?: unknown; exp?: unknown };
    if (typeof sub !== "string" || !sub) return null;
    if (typeof exp !== "number" || exp <= Math.floor(Date.now() / 1000)) return null;

    return sub;
  } catch {
    return null;
  }
}
