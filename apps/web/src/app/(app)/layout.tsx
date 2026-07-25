import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/features/navigation/app-shell";

/**
 * Layout for every authenticated route.
 *
 * The middleware already protects these paths. This check is deliberate
 * duplication: it is the layer that survives a mistake in the middleware
 * matcher, and an unprotected page fails silently — it renders, serves data,
 * and reports nothing wrong.
 */
export default async function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const { userId } = await auth();

  if (!userId) {
    redirect("/sign-in");
  }

  return <AppShell>{children}</AppShell>;
}
