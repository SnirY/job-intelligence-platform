"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Sign-in for the local authentication mode.
 *
 * There is no password, because there is nothing to check one against: this
 * mode exists so the system can be opened without registering with an identity
 * provider. The name chosen here becomes the token's `sub`, which the API turns
 * into a user row on first sight — the same provisioning path a real issuer
 * goes through.
 *
 * Two people typing different names get two separate profiles, which is what
 * makes this usable for a demo where several people look at the same instance
 * without seeing each other's data.
 */
export function LocalSignInForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startSession(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const response = await fetch("/api/local-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(name.trim() ? { subject: name.trim(), name: name.trim() } : {}),
      });

      if (!response.ok) {
        const body: unknown = await response.json().catch(() => null);
        const message =
          typeof body === "object" && body !== null && "error" in body
            ? String((body as { error: unknown }).error)
            : "Could not start a local session.";
        setError(message);
        return;
      }

      // `refresh` first: the authenticated layout reads the cookie on the
      // server, and without it Next can answer /home from a cache populated
      // while there was no session.
      router.refresh();
      router.push("/home");
    } catch {
      setError("Could not reach the local session endpoint.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={startSession} className="w-full max-w-sm space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted-foreground text-pretty">
          This instance runs in local mode — no account, no password. Pick a name and it becomes
          your profile. Use the same name again to come back to it.
        </p>
      </div>

      <div className="space-y-2">
        <label htmlFor="local-subject" className="text-sm font-medium">
          Your name
        </label>
        <input
          id="local-subject"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="demo"
          autoComplete="off"
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
        />
        <p className="text-xs text-muted-foreground">
          Leave it empty to use the shared demo profile.
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <Button type="submit" size="lg" className="w-full" disabled={pending}>
        {pending ? "Signing in…" : "Continue"}
      </Button>
    </form>
  );
}
