import { SignUp } from "@clerk/nextjs";

/** Sign-up. Catch-all for the same reason as sign-in. */
export default function SignUpPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <SignUp signInUrl="/sign-in" fallbackRedirectUrl="/home" />
    </main>
  );
}
