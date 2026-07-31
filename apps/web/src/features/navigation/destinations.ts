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

export const CURRENT_PHASE = 8;
/** The last phase that has shipped.
 *
 * Exists because it was previously written out by hand on the landing page and
 * went stale for two whole phases — the page still said "Phase 6" after resume
 * tailoring and application tracking had both shipped, claiming the product did
 * less than it does. Nothing enforced the comment above it that said to keep it
 * accurate.
 *
 * One number, read by everything that describes progress, and asserted against
 * the destination table below. Bump it when a phase merges. */

export const TOTAL_PHASES = 11;

/** A destination in the main navigation. */
export interface Destination {
  href: string;
  label: string;
  icon: LucideIcon;
  /** The phase that will make this destination functional. */
  availableInPhase: number;
  /** How the landing page names this capability, in the user's terms.
   *
   * Lives beside the phase it depends on so the two cannot drift apart — the
   * sentence and the availability are one fact, described once. */
  landingSummary: string;
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
  {
    href: "/home",
    label: "Home",
    icon: Home,
    availableInPhase: 9,
    landingSummary: "see where everything stands",
  },
  {
    href: "/jobs",
    label: "Jobs",
    icon: Briefcase,
    availableInPhase: 4,
    landingSummary: "save jobs and have a posting read into its requirements",
  },
  {
    href: "/applications",
    label: "Applications",
    icon: Send,
    availableInPhase: 8,
    landingSummary: "track where each application stands",
  },
  {
    href: "/resumes",
    label: "Resumes",
    icon: FileText,
    availableInPhase: 7,
    landingSummary: "tailor a resume for one job",
  },
  {
    href: "/career-profile",
    label: "Career Profile",
    icon: UserRound,
    availableInPhase: 2,
    landingSummary: "build a career profile or import one from a resume",
  },
  {
    href: "/insights",
    label: "Insights",
    icon: LineChart,
    availableInPhase: 10,
    landingSummary: "career insights",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    availableInPhase: 11,
    landingSummary: "settings",
  },
] as const;

/**
 * True when `pathname` is within `href`.
 *
 * Compares whole segments so `/jobs` does not light up for `/jobs-archive`.
 */
export function isActiveDestination(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The destinations that do something today, and the ones still to come.
 *
 * Derived from the phase each destination waits on, so a page describing the
 * product's progress cannot disagree with the navigation beside it. Home is
 * excluded from both: it exists from Phase 1 and grows into a dashboard in
 * Phase 9, so it is never "not built" and never quite finished either.
 */
export function destinationsByAvailability(phase: number = CURRENT_PHASE): {
  available: Destination[];
  upcoming: Destination[];
} {
  // Ordered by the phase each arrived in, which is also the order a user meets
  // them: build a profile, save a job, tailor a resume, track the application.
  // The navigation's own order is a different question — it puts the most
  // visited first.
  const relevant = DESTINATIONS.filter((destination) => destination.href !== "/home")
    .slice()
    .sort((a, b) => a.availableInPhase - b.availableInPhase);

  return {
    available: relevant.filter((destination) => destination.availableInPhase <= phase),
    upcoming: relevant.filter((destination) => destination.availableInPhase > phase),
  };
}
