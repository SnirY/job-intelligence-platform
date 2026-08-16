// @vitest-environment node
//
// No DOM here. `vitest.config.mts` sets jsdom for every file, which is right
// for the component tests and pure cost for this one — DEV-058 measured jsdom
// setup as the dominant shared expense in a parallel run. Overriding it per
// file is the supported way to opt out.
import { describe, expect, it } from "vitest";

import {
  CURRENT_PHASE,
  DESTINATIONS,
  TOTAL_PHASES,
  destinationsByAvailability,
  isActiveDestination,
} from "@/features/navigation/destinations";

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

/**
 * The landing page said "Phase 6" for two phases after resume tailoring and
 * application tracking had both shipped, because the sentence was written out
 * by hand and a comment asked the next person to keep it current. These make
 * that impossible rather than asking again.
 */
describe("what the product claims about itself", () => {
  it("splits destinations into built and unbuilt at the current phase", () => {
    const { available, upcoming } = destinationsByAvailability();

    // In the order a user meets them, not the navigation's order.
    expect(available.map((d) => d.label)).toEqual([
      "Career Profile",
      "Jobs",
      "Resumes",
      "Applications",
      "Insights",
      // Phase 11. Specified in four documents and scheduled in none until
      // DEV-035 — it sat in `upcoming` for eleven phases and nothing here could
      // tell that apart from a destination whose turn had not come.
      "Settings",
    ]);
    expect(upcoming).toEqual([]);
  });

  it("never describes a shipped destination as unbuilt", () => {
    // The exact failure that occurred. Phrased over every phase so it fails on
    // the release that forgets to move CURRENT_PHASE, not only on this one.
    for (let phase = 1; phase <= TOTAL_PHASES; phase += 1) {
      const { available, upcoming } = destinationsByAvailability(phase);
      const overlap = available.filter((d) => upcoming.includes(d));

      expect(overlap).toEqual([]);
    }
  });

  it("keeps every destination accounted for at the current phase", () => {
    const { available, upcoming } = destinationsByAvailability();

    // Home is deliberately in neither: it exists from Phase 1 and becomes a
    // dashboard in Phase 9, so it is never "not built" and never finished.
    expect(available.length + upcoming.length).toBe(DESTINATIONS.length - 1);
  });

  it("gives every destination a sentence the landing page can use", () => {
    // A destination without one would silently render an empty clause.
    for (const destination of DESTINATIONS) {
      expect(destination.landingSummary.trim()).not.toBe("");
    }
  });

  it("has not shipped a phase that does not exist", () => {
    expect(CURRENT_PHASE).toBeGreaterThan(0);
    expect(CURRENT_PHASE).toBeLessThanOrEqual(TOTAL_PHASES);
  });

  it("matches the phase every shipped destination waits on", () => {
    // If a destination ships, CURRENT_PHASE must have reached its phase. This
    // is what fails when a phase merges and the constant is not bumped.
    //
    // Home is included. It was excluded while it was a placeholder reachable
    // from Phase 1, and that exclusion made this assertion blind to the one
    // phase whose entire deliverable is Home — which is exactly what it missed
    // when Phase 9 shipped.
    const shipped = DESTINATIONS.filter((d) => d.availableInPhase <= CURRENT_PHASE);

    expect(Math.max(...shipped.map((d) => d.availableInPhase))).toBe(CURRENT_PHASE);
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
