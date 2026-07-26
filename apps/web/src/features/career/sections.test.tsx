import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EducationSection } from "@/features/career/education-section";
import { ExperienceSection } from "@/features/career/experience-section";
import { ProjectsSection } from "@/features/career/projects-section";
import { SkillsSection } from "@/features/career/skills-section";
import { formatDateRange } from "@/features/career/section";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: vi.fn().mockResolvedValue("token") }),
}));

function list(items: unknown[]) {
  return { ok: true, status: 200, json: async () => ({ data: items }) };
}

function renderSection(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const SECTIONS = [
  { name: "Skills", Component: SkillsSection, empty: /No skills yet/ },
  { name: "Experience", Component: ExperienceSection, empty: /No experience yet/ },
  { name: "Projects", Component: ProjectsSection, empty: /No projects yet/ },
  { name: "Education", Component: EducationSection, empty: /No education yet/ },
];

describe.each(SECTIONS)("$name section", ({ name, Component, empty }) => {
  it("invites a first entry when the collection is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(list([])));

    renderSection(<Component />);

    expect(await screen.findByText(empty)).toBeInTheDocument();
  });

  it("shows a loading state before data arrives", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderSection(<Component />);

    expect(screen.getByText(new RegExp(`Loading ${name.toLowerCase()}`))).toBeInTheDocument();
  });

  it("surfaces a load failure instead of showing an empty list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderSection(<Component />);

    expect(
      await screen.findByText(new RegExp(`Could not load ${name.toLowerCase()}`)),
    ).toBeInTheDocument();
    expect(screen.queryByText(empty)).not.toBeInTheDocument();
  });
});

describe("SkillsSection", () => {
  it("keeps submit disabled until a name is entered", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(list([])));

    renderSection(<SkillsSection />);

    const submit = await screen.findByRole("button", { name: /Add skill/ });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Skill"), "Python");
    expect(submit).toBeEnabled();
  });

  it("posts a trimmed name", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(list([]))
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ data: {} }) })
      .mockResolvedValue(list([]));
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<SkillsSection />);

    await userEvent.type(await screen.findByLabelText("Skill"), "  Python  ");
    await userEvent.click(screen.getByRole("button", { name: /Add skill/ }));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(init.body as string).name).toBe("Python");
  });

  it("explains a duplicate skill rather than failing silently", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(list([]))
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: { code: "CONFLICT", message: "already", details: null, request_id: "r" },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<SkillsSection />);

    await userEvent.type(await screen.findByLabelText("Skill"), "Python");
    await userEvent.click(screen.getByRole("button", { name: /Add skill/ }));

    expect(await screen.findByText("That skill is already in your list.")).toBeInTheDocument();
  });

  it("renders the verification badge from the stored status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        list([
          {
            id: "1",
            skill_id: "s1",
            name: "Python",
            category: "LANGUAGE",
            proficiency: "ADVANCED",
            years_of_experience: 3,
            last_used_year: null,
            verification_status: "USER_CONFIRMED",
            source: "MANUAL",
            notes: null,
          },
        ]),
      ),
    );

    renderSection(<SkillsSection />);

    expect(await screen.findByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText(/Language · Advanced · 3y/)).toBeInTheDocument();
  });
});

describe("ExperienceSection", () => {
  it("clears and disables the end date when the role is current", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(list([])));

    renderSection(<ExperienceSection />);

    const endDate = await screen.findByLabelText("End date");
    await userEvent.type(endDate, "2024-01-01");

    await userEvent.click(screen.getByLabelText("I currently work here"));

    expect(endDate).toBeDisabled();
    expect(endDate).toHaveValue("");
  });

  it("requires both a title and a company", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(list([])));

    renderSection(<ExperienceSection />);

    const submit = await screen.findByRole("button", { name: /Add experience/ });
    await userEvent.type(screen.getByLabelText("Title"), "Engineer");
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Company"), "Acme");
    expect(submit).toBeEnabled();
  });
});

describe("ProjectsSection", () => {
  it("marks external repository links noopener noreferrer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        list([
          {
            id: "1",
            name: "Portfolio",
            project_type: "PERSONAL",
            status: "COMPLETED",
            summary: null,
            description: null,
            start_date: null,
            end_date: null,
            repository_url: "https://github.com/example/repo",
            demo_url: null,
            documentation_url: null,
            verification_status: "USER_CONFIRMED",
          },
        ]),
      ),
    );

    renderSection(<ProjectsSection />);

    const link = await screen.findByRole("link", { name: "Repository" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("formatDateRange", () => {
  it("shows Present for a current entry", () => {
    expect(formatDateRange("2022-03-01", null, true)).toBe("2022-03 – Present");
  });

  it("shows a closed range", () => {
    expect(formatDateRange("2020-01-01", "2022-06-01")).toBe("2020-01 – 2022-06");
  });

  it("returns null when there are no dates", () => {
    expect(formatDateRange(null, null)).toBeNull();
  });
});
