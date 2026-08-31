import { cookies } from "next/headers";

import { LOCAL_SESSION_COOKIE } from "@/lib/auth-mode";
import { localSecret, verifyLocalToken } from "@/lib/local-token";

/**
 * The signed-in subject in local mode, or `null`.
 *
 * Server-side counterpart to reading the cookie in the browser. The token is
 * verified rather than merely present: a stale or hand-edited cookie should
 * fail the gate here, not render a whole authenticated shell that then 401s on
 * its first request.
 */
export async function localSessionSubject(): Promise<string | null> {
  const secret = localSecret();
  if (!secret) return null;

  const token = (await cookies()).get(LOCAL_SESSION_COOKIE)?.value;
  if (!token) return null;

  return verifyLocalToken(secret, token);
}
