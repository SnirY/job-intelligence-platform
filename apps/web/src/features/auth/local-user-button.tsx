"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Sign-out for the local authentication mode.
 *
 * Stands in for Clerk's `UserButton`, which needs a Clerk instance behind it.
 * There is no account to manage here — a local session is a name and an expiry
 * — so the menu that button opens would have exactly one item in it. This is
 * that item.
 */
export function LocalUserButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function endSession() {
    setPending(true);
    try {
      await fetch("/api/local-session", { method: "DELETE" });
      router.refresh();
      router.push("/sign-in");
    } finally {
      setPending(false);
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={endSession}
      disabled={pending}
      aria-label="Sign out"
      title="Sign out"
    >
      <LogOut aria-hidden className="size-5" />
    </Button>
  );
}
