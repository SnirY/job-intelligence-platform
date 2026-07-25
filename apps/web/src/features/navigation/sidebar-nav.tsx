"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DESTINATIONS, isActiveDestination } from "@/features/navigation/destinations";
import { cn } from "@/lib/utils";

interface SidebarNavProps {
  /** Called after a destination is chosen, so the mobile drawer can close. */
  onNavigate?: () => void;
}

export function SidebarNav({ onNavigate }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex flex-col gap-1 p-3">
      {DESTINATIONS.map(({ href, label, icon: Icon }) => {
        const active = isActiveDestination(pathname, href);

        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            // aria-current carries the active state for screen readers; the
            // colour change alone would not.
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "bg-secondary text-secondary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            <Icon aria-hidden className="size-4 shrink-0" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
