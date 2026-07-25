import { describe, expect, it } from "vitest";

import { DESTINATIONS, isActiveDestination } from "@/features/navigation/destinations";

describe("navigation destinations", () => {
  it("matches the navigation set in docs/02-user-flows.md", () => {
    expect(DESTINATIONS.map((destination) => destination.label)).toEqual([
      "Home",
      "Jobs",
      "Applications",
      "Resumes",
      "Career Profile",
      "Insights",
      "Settings",
    ]);
  });

  it("routes every destination to a distinct path", () => {
    const paths = DESTINATIONS.map((destination) => destination.href);

    expect(new Set(paths).size).toBe(paths.length);
  });
});

describe("isActiveDestination", () => {
  it("matches the exact path", () => {
    expect(isActiveDestination("/jobs", "/jobs")).toBe(true);
  });

  it("matches nested paths", () => {
    expect(isActiveDestination("/jobs/abc-123", "/jobs")).toBe(true);
  });

  it("does not match a path that merely shares a prefix", () => {
    // "/jobs-archive" starts with "/jobs" as a string but is a different
    // destination; a naive startsWith would highlight the wrong nav item.
    expect(isActiveDestination("/jobs-archive", "/jobs")).toBe(false);
  });

  it("does not match an unrelated path", () => {
    expect(isActiveDestination("/insights", "/jobs")).toBe(false);
  });
});
