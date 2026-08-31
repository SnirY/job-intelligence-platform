import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/features/navigation/app-shell";
import { isLocalAuth } from "@/lib/auth-mode";
import { localSessionSubject } from "@/lib/local-session.server";

/**
 * Layout for every authenticated route.
 *
 * The middleware already protects these paths. This check is deliberate
 * duplication: it is the layer that survives a mistake in the middleware
 * matcher, and an unprotected page fails silently — it renders, serves data,
 * and reports nothing wrong.
 *
 * That duplication is what lets local mode drop the middleware entirely: this
 * gate is the one that was doing the work, and it applies the same rule to
 * whichever session type the build uses.
 */
export default async function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const signedIn = isLocalAuth ? await localSessionSubject() : (await auth()).userId;

  if (!signedIn) {
    redirect("/sign-in");
  }

  return <AppShell>{children}</AppShell>;
}
