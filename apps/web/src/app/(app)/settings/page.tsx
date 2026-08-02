import { PhasePlaceholder } from "@/components/phase-placeholder";

/**
 * Career preferences, once they exist.
 *
 * This page said "arriving in Phase 11" before Phase 11 said anything about
 * settings — `docs/09` listed seven hardening focuses and no screen. The claim
 * was true by coincidence and is now true by schedule: DEV-035 found that
 * `CareerPreferences` is specified in four documents and built in none, and
 * scheduled it here.
 *
 * The description below is deliberately concrete about what will be here. The
 * previous one described the page by what it was not ("sign-out is elsewhere"),
 * which is how a placeholder for a feature nobody had scheduled survived
 * eleven phases looking deliberate.
 */
export default function SettingsPage() {
  return (
    <PhasePlaceholder
      title="Settings"
      phase={11}
      phaseName="Production Hardening"
      description="Work mode, employment type, locations, salary expectations and role types to exclude — the preferences a recommendation should account for. Account details and sign-out are in the avatar menu."
    />
  );
}
