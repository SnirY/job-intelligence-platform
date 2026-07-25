import { clerkMiddleware } from "@clerk/nextjs/server";

/**
 * Attaches the Clerk auth context to every request.
 *
 * It deliberately does **not** decide who may see what. Clerk deprecated
 * `createRouteMatcher` for exactly that job, because middleware protection is
 * path matching, and path matching can diverge from how Next.js actually routes
 * a request — leaving a protected resource reachable with nothing logged.
 *
 * Authorization therefore lives with the resource: `src/app/(app)/layout.tsx`
 * checks the session before rendering any authenticated page, and the API
 * verifies the bearer token independently. A page added under `(app)/` is
 * protected because of where it lives, not because someone remembered to update
 * a regex here.
 *
 * On Next.js 16 this file is renamed to `proxy.ts`. A middleware file Next does
 * not load provides no auth context at all, so that rename is a required step
 * of the upgrade.
 */
export default clerkMiddleware();

export const config = {
  matcher: [
    // Everything except Next internals and static files, which carry no user
    // data and would only add latency.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
