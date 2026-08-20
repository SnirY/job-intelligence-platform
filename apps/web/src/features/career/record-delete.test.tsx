import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CertificationsSection } from "@/features/career/certifications-section";
import { EducationSection } from "@/features/career/education-section";
import { ExperienceSection } from "@/features/career/experience-section";
import { ProjectsSection } from "@/features/career/projects-section";
import { SkillsSection } from "@/features/career/skills-section";

/**
 * Which career deletes ask first, and which deliberately do not.
 *
 * Both halves are asserted, because the second is the one that decays. F29 was
 * fixed with an argument that cuts both ways: a product asking "are you sure?"
 * about everything has taught people to click through the one question that
 * mattered, so a test that only proves dialogs exist would happily watch them
 * spread onto every row until none of them is read.
 *
 * The line is whether deleting destroys composed prose, or rows hanging off
 * the record, rather than facts the list is already showing.
 */

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function renderSection(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function server(items: unknown[]) {
  const calls: Array<{ url: string; method: string }> = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET" });
    return { ok: true, status: 200, json: async () => ({ data: items }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function deleted(calls: Array<{ url: string; method: string }>) {
  return calls.some((call) => call.method === "DELETE");
}

const EXPERIENCE = {
  id: "exp-1",
  company: "Verdant",
  title: "Backend Engineer",
  employment_type: "FULL_TIME",
  location: "Lisbon",
  start_date: "2021-01-01",
  end_date: null,
  is_current: true,
  description: "Routing services.",
  verification_status: "USER_CONFIRMED",
  achievements: [
    {
      id: "a1",
      text: "Cut p99 latency by half.",
      display_order: 0,
      verification_status: "USER_CONFIRMED",
    },
    {
      id: "a2",
      text: "Mentored two juniors.",
      display_order: 1,
      verification_status: "USER_CONFIRMED",
    },
  ],
};

const PROJECT = {
  id: "proj-1",
  name: "Stereo depth pipeline",
  project_type: null,
  status: null,
  summary: "Real-time depth from a stereo rig.",
  description: "Written in C++ and Python.",
  start_date: null,
  end_date: null,
  repository_url: null,
  demo_url: null,
  documentation_url: null,
  verification_status: "USER_CONFIRMED",
  skills: ["C++", "Python"],
};

const SKILL = {
  id: "skill-1",
  skill_id: "canon-1",
  name: "Python",
  category: "LANGUAGE",
  proficiency: "ADVANCED",
  years_of_experience: 6,
  last_used_year: 2026,
  verification_status: "USER_CONFIRMED",
  source: "MANUAL",
  notes: null,
};

const EDUCATION = {
  id: "edu-1",
  institution: "Technion",
  degree: "BSc",
  field_of_study: "Software Engineering",
  start_date: "2016-10-01",
  end_date: "2020-07-01",
  grade: null,
  description: null,
  verification_status: "USER_CONFIRMED",
};

const CERTIFICATION = {
  id: "cert-1",
  name: "AWS Solutions Architect",
  issuer: "Amazon",
  issued_date: "2024-01-01",
  expiry_date: null,
  credential_id: null,
  credential_url: null,
  verification_status: "USER_CONFIRMED",
};

afterEach(() => vi.unstubAllGlobals());

describe("records whose deletion takes more than the row shows", () => {
  it("asks before deleting a role, and counts the achievements nobody can see", async () => {
    /* The list renders a title, a company and dates. The achievements and the
       description live in the edit form, which is shut, and
       experience_achievements cascades. That is paragraphs somebody wrote,
       invisible from the button that removes them. */
    const calls = server([EXPERIENCE]);

    renderSection(<ExperienceSection />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Backend Engineer at Verdant" }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/2 achievements you wrote/)).toBeInTheDocument();
    expect(deleted(calls)).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted(calls)).toBe(true));
  });

  it("asks before deleting a project whose write-up is not in the row", async () => {
    const calls = server([PROJECT]);

    renderSection(<ProjectsSection />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Stereo depth pipeline" }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/write-up goes with it/)).toBeInTheDocument();
    expect(deleted(calls)).toBe(false);
  });

  it("asks before deleting a skill, and names the cascade without counting it", async () => {
    /* skill_evidence cascades, and the evidence list loads per skill only when
       its panel is opened. Fetching to fill a sentence would make every delete
       button cost a request, so the sentence does without a number. The
       cascade is real whether or not anyone has counted it. */
    const calls = server([SKILL]);

    renderSection(<SkillsSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Python" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/reasons you recorded/i)).toBeInTheDocument();
    expect(deleted(calls)).toBe(false);
  });

  it("deletes nothing when the question is declined", async () => {
    const calls = server([EXPERIENCE]);

    renderSection(<ExperienceSection />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Remove Backend Engineer at Verdant" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleted(calls)).toBe(false);
  });
});

describe("records where the row is the whole record", () => {
  /* Asserted as absence on purpose. Every field is a fact already on screen,
     nothing cascades, and retyping one takes about as long as reading a dialog
     about it. If these ever grow a confirmation it should be because something
     started hanging off them — not because confirmations spread. */

  it("deletes education without asking", async () => {
    const calls = server([EDUCATION]);

    renderSection(<EducationSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Technion" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(deleted(calls)).toBe(true));
  });

  it("deletes a certification without asking", async () => {
    const calls = server([CERTIFICATION]);

    renderSection(<CertificationsSection />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Remove AWS Solutions Architect/ }),
    );

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(deleted(calls)).toBe(true));
  });
});
