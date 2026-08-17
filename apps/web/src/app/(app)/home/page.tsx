import { currentUser } from "@clerk/nextjs/server";

import { DashboardScreen } from "@/features/dashboard/dashboard";

/**
 * Home.
 *
 * The greeting resolves on the server because Clerk has the name there without
 * a round trip. Everything else is the dashboard's own query — rendering it
 * server-side would block the whole page on the slowest aggregate and then have
 * to revalidate on the client anyway.
 *
 * The account and API status cards this page used to show have gone. They were
 * here because there was nothing else true to show yet; now there is, and a
 * connection indicator on a working home screen is noise.
 */
export default async function HomePage() {
  const user = await currentUser();

  // The name only. Whether the reader is returning is a question about their
  // data, and the dashboard is what holds it — see `greet` there.
  return <DashboardScreen firstName={user?.firstName ?? null} />;
}
