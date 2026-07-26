import { EducationSection } from "@/features/career/education-section";
import { ExperienceSection } from "@/features/career/experience-section";
import { ProfileBasicsForm } from "@/features/career/profile-basics-form";
import { ProjectsSection } from "@/features/career/projects-section";
import { SkillsSection } from "@/features/career/skills-section";
import { TargetRolesSection } from "@/features/career/target-roles-section";

export default function CareerProfilePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Career Profile</h1>
        <p className="text-muted-foreground">
          Your skills, experience, projects, and evidence — the source of truth every job match is
          measured against. Everything here is yours to edit; nothing is generated.
        </p>
      </header>

      <ProfileBasicsForm />
      <TargetRolesSection />
      <SkillsSection />
      <ExperienceSection />
      <ProjectsSection />
      <EducationSection />
    </div>
  );
}
