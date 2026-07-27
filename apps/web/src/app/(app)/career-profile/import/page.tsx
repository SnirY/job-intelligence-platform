import Link from "next/link";

import { ImportWorkspace } from "@/features/resume-import/import-workspace";

/**
 * Resume import lives under the career profile, not under Resumes.
 *
 * `docs/02-user-flows.md` puts "Import Resume → Review Extracted Profile" in
 * onboarding, feeding the profile. The Resumes destination is Phase 7's resume
 * *authoring*, which is a different job.
 */
export default function ResumeImportPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <Link
          href="/career-profile"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          ← Career Profile
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Import from a resume</h1>
        <p className="text-muted-foreground">
          Save typing by reading an existing resume. We propose what we found and you decide what
          goes on your profile — nothing is added without your say-so, and we never add a detail
          your document does not contain.
        </p>
      </header>

      <ImportWorkspace />
    </div>
  );
}
