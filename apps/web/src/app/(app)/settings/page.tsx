import { PreferencesForm } from "@/features/career/preferences-form";

/**
 * Career preferences.
 *
 * A `PhasePlaceholder` until now, and for eleven phases the placeholder was the
 * only part anyone noticed was missing. `CareerPreferences` is specified in four
 * documents — `docs/01`, `docs/02`, `docs/03` and `docs/05` — and was scheduled
 * in none of them, which is DEV-035.
 *
 * Account identity and sign-out stay in the avatar menu, where Clerk owns them.
 * Nothing here duplicates a control that already exists elsewhere.
 */
export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          What you will and will not take. Every job you save is read against these, beside its
          match — and where a posting does not say, we say so rather than assuming it fits.
        </p>
      </header>

      <PreferencesForm />
    </div>
  );
}
