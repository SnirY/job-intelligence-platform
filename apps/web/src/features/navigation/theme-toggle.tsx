"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Light, dark, or whatever the operating system says.
 *
 * DEV-056. `globals.css` has carried a full `.dark` palette since Phase 0 and
 * nothing ever added the class, so `docs/08-ui-ux.md`'s "design for both from
 * the beginning" was half true for eleven phases.
 *
 * Three states rather than two. A two-way switch has to start somewhere, and
 * whichever it picks is a claim about the reader that the reader has already
 * answered in their own settings — `system` is that answer, and it stays
 * correct when they change it later in the day.
 */
const ORDER = ["system", "light", "dark"] as const;

const LABELS: Record<(typeof ORDER)[number], string> = {
  system: "Theme: match system",
  light: "Theme: light",
  dark: "Theme: dark",
};

const ICONS: Record<(typeof ORDER)[number], typeof Sun> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  // Rendered only after mount. The server cannot know the reader's system
  // preference, so anything drawn before hydration is a guess that will be
  // wrong half the time — and a control that changes under the cursor is worse
  // than one that arrives a frame late. The placeholder holds the width so the
  // header does not shift.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="size-9" aria-hidden />;
  }

  const current = (ORDER as readonly string[]).includes(theme ?? "")
    ? (theme as (typeof ORDER)[number])
    : "system";
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system";
  const Icon = ICONS[current];

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(next)}
      // The label says the current state, not the action. A control announcing
      // "switch to dark" leaves a screen-reader user with no way to ask what it
      // is now, which is the question the icon answers for everyone else.
      aria-label={LABELS[current]}
      title={LABELS[current]}
    >
      <Icon aria-hidden className="size-5" />
    </Button>
  );
}
