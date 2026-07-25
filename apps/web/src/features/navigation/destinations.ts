import {
  Briefcase,
  FileText,
  Home,
  LineChart,
  Send,
  Settings,
  UserRound,
  type LucideIcon,
} from "lucide-react";

/** A destination in the main navigation. */
export interface Destination {
  href: string;
  label: string;
  icon: LucideIcon;
  /** The phase that will make this destination functional. */
  availableInPhase: number;
}

/**
 * Main navigation, in the order given by `docs/02-user-flows.md` and
 * `docs/08-ui-ux.md`.
 *
 * Every destination routes to a real page. Pages whose phase has not arrived
 * say so plainly rather than showing invented data — a placeholder dashboard
 * full of fake numbers is worse than an empty one, because it cannot be told
 * apart from a broken real one.
 */
export const DESTINATIONS: readonly Destination[] = [
  { href: "/home", label: "Home", icon: Home, availableInPhase: 9 },
  { href: "/jobs", label: "Jobs", icon: Briefcase, availableInPhase: 4 },
  { href: "/applications", label: "Applications", icon: Send, availableInPhase: 8 },
  { href: "/resumes", label: "Resumes", icon: FileText, availableInPhase: 7 },
  { href: "/career-profile", label: "Career Profile", icon: UserRound, availableInPhase: 2 },
  { href: "/insights", label: "Insights", icon: LineChart, availableInPhase: 10 },
  { href: "/settings", label: "Settings", icon: Settings, availableInPhase: 11 },
] as const;

/**
 * True when `pathname` is within `href`.
 *
 * Compares whole segments so `/jobs` does not light up for `/jobs-archive`.
 */
export function isActiveDestination(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
