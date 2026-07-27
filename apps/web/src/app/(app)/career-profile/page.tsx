import { FileUp } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
          measured against. Everything here is yours to edit, and nothing appears without your
          approval.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Already have a resume?</CardTitle>
          <CardDescription>
            Read it once instead of typing everything twice. You review every detail before it
            reaches your profile.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="secondary">
            <Link href="/career-profile/import">
              <FileUp aria-hidden className="size-4" />
              Import from a resume
            </Link>
          </Button>
        </CardContent>
      </Card>

      <ProfileBasicsForm />
      <TargetRolesSection />
      <SkillsSection />
      <ExperienceSection />
      <ProjectsSection />
      <EducationSection />
    </div>
  );
}
