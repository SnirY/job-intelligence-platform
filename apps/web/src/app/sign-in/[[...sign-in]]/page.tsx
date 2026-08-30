import { SignIn } from "@clerk/nextjs";

import { LocalSignInForm } from "@/features/auth/local-sign-in-form";
import { isLocalAuth } from "@/lib/auth-mode";

/**
 * Sign-in.
 *
 * The catch-all segment is required: Clerk routes its multi-step flows
 * (verification, factor two, recovery) as sub-paths of this route. Local mode
 * has no such flows and renders a single form at the same path, so every
 * `redirect("/sign-in")` in the app stays correct in both modes.
 */
export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      {isLocalAuth ? (
        <LocalSignInForm />
      ) : (
        <SignIn signUpUrl="/sign-up" fallbackRedirectUrl="/home" />
      )}
    </main>
  );
}
