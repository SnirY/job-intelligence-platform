import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { isLocalAuth, LOCAL_SESSION_COOKIE } from "@/lib/auth-mode";
import { DEFAULT_SUBJECT, localSecret, mintLocalToken } from "@/lib/local-token";

/**
 * Starts and ends a local session.
 *
 * The token is minted here rather than in the browser because minting needs the
 * shared secret, and the browser is exactly where that must not be. The client
 * posts a name and receives a cookie.
 *
 * Every route in this file refuses unless the build is in local mode, so a
 * deployment that forgets to remove it still has no way to mint anything.
 */

const SESSION_TTL_SECONDS = 86_400;

function refuseUnlessLocal(): NextResponse | null {
  if (!isLocalAuth) {
    return NextResponse.json(
      { error: "This build does not use local authentication." },
      { status: 404 },
    );
  }
  return null;
}

export async function POST(request: Request): Promise<NextResponse> {
  const refusal = refuseUnlessLocal();
  if (refusal) return refusal;

  const secret = localSecret();
  if (!secret) {
    return NextResponse.json(
      { error: "AUTH_LOCAL_SECRET is not set, or is shorter than 32 characters." },
      { status: 500 },
    );
  }

  let subject = DEFAULT_SUBJECT;
  let displayName: string | undefined;
  try {
    const body: unknown = await request.json();
    if (typeof body === "object" && body !== null) {
      const { subject: requested, name } = body as { subject?: unknown; name?: unknown };
      if (typeof requested === "string" && requested.trim()) subject = requested.trim();
      if (typeof name === "string" && name.trim()) displayName = name.trim();
    }
  } catch {
    // An empty or unparseable body means "the default demo user", which is the
    // common case and not worth an error.
  }

  const token = mintLocalToken(secret, { sub: subject, name: displayName }, SESSION_TTL_SECONDS);

  const store = await cookies();
  store.set(LOCAL_SESSION_COOKIE, token, {
    // Deliberately readable by client JavaScript: `useApi` puts this token in
    // an Authorization header, so an httpOnly cookie would need every API call
    // proxied through Next to reach the backend at all. Acceptable only because
    // this mode already treats one shared secret as the credential — it is why
    // the API refuses to build this verifier outside local and test.
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });

  return NextResponse.json({ subject });
}

export async function DELETE(): Promise<NextResponse> {
  const refusal = refuseUnlessLocal();
  if (refusal) return refusal;

  const store = await cookies();
  store.delete(LOCAL_SESSION_COOKIE);

  return NextResponse.json({ ended: true });
}
