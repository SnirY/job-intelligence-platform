import { ProfileBasicsForm } from "@/features/career/profile-basics-form";
import { TargetRolesSection } from "@/features/career/target-roles-section";

export default function CareerProfilePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Career Profile</h1>
        <p className="text-muted-foreground">
          Your skills, experience, projects, and evidence — the source of truth every job match is
          measured against.
        </p>
      </header>

      <ProfileBasicsForm />
      <TargetRolesSection />

      {/*
        Skills, experience, projects, and education are the remaining Phase 2
        slices. They are absent rather than stubbed: an empty section that looks
        built is indistinguishable from a broken one.
      */}
    </div>
  );
}
