import { currentUser } from "@clerk/nextjs/server";

import { AccountStatusCard } from "@/features/system/account-status-card";
import { ApiStatusCard } from "@/features/system/api-status-card";

/**
 * Home.
 *
 * The dashboard proper arrives in Phase 9. Until there is real career data to
 * summarise, this page shows only what genuinely exists: the state of the
 * user's session and of the backend connection.
 */
export default async function HomePage() {
  const user = await currentUser();
  const greeting = user?.firstName ? `Welcome back, ${user.firstName}` : "Welcome back";

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{greeting}</h1>
        <p className="text-muted-foreground">
          Your account is set up. The career and job features arrive in the phases listed in each
          section of the navigation.
        </p>
      </header>

      <div className="grid gap-4">
        <AccountStatusCard />
        <ApiStatusCard />
      </div>
    </div>
  );
}
