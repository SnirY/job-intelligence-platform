import { SignIn } from "@clerk/nextjs";

/**
 * Sign-in.
 *
 * The catch-all segment is required: Clerk routes its multi-step flows
 * (verification, factor two, recovery) as sub-paths of this route.
 */
export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <SignIn signUpUrl="/sign-up" fallbackRedirectUrl="/home" />
    </main>
  );
}
