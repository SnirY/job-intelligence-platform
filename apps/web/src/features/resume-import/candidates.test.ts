import type { CandidateType, ExtractionItem } from "@jip/shared-types";
import { describe, expect, it } from "vitest";

import {
  candidateDetail,
  candidateTitle,
  childrenOf,
  datePrecisionNote,
  editableFields,
  effectivePayload,
  isDecided,
  readFlags,
  topLevelOfType,
} from "@/features/resume-import/candidates";

function item(overrides: Partial<ExtractionItem> = {}): ExtractionItem {
  return {
    id: "item-1",
    candidate_type: "SKILL",
    parent_item_id: null,
    display_order: 0,
    payload: { name: "Python" },
    edited_payload: null,
    confidence: 90,
    source_text: null,
    decision: "PENDING",
    target_entity_type: null,
    target_entity_id: null,
    ...overrides,
  };
}

describe("effectivePayload", () => {
  it("returns the extraction when nothing was edited", () => {
    expect(effectivePayload(item())).toEqual({ name: "Python" });
  });

  it("prefers the edit, because that is what an approval writes", () => {
    const edited = item({ edited_payload: { name: "Python 3" } });

    expect(effectivePayload(edited)).toEqual({ name: "Python 3" });
  });
});

describe("candidateTitle", () => {
  const cases: Array<[CandidateType, Partial<ExtractionItem>, string]> = [
    ["SKILL", { payload: { name: "Python" } }, "Python"],
    [
      "EXPERIENCE",
      { payload: { title: "Backend Engineer", company: "Verdant" } },
      "Backend Engineer · Verdant",
    ],
    ["EXPERIENCE_ACHIEVEMENT", { payload: { text: "Shipped the thing." } }, "Shipped the thing."],
    ["PROJECT", { payload: { name: "ledgerline" } }, "ledgerline"],
    ["PROJECT_SKILL", { payload: { name: "SQLAlchemy" } }, "SQLAlchemy"],
    [
      "EDUCATION",
      { payload: { degree: "BSc", field_of_study: "Computer Science" } },
      "BSc, Computer Science",
    ],
  ];

  it.each(cases)("renders a %s", (candidateType, overrides, expected) => {
    expect(candidateTitle(item({ candidate_type: candidateType, ...overrides }))).toBe(expected);
  });

  it("never renders blank, even for an unexpected payload", () => {
    expect(candidateTitle(item({ payload: {} }))).toBe("Untitled");
  });
});

describe("candidateDetail", () => {
  it("shows a role's location and dates", () => {
    const experience = item({
      candidate_type: "EXPERIENCE",
      payload: {
        title: "Backend Engineer",
        company: "Verdant",
        location: "Lisbon",
        start_date: "2023-03-01",
        is_current: true,
      },
    });

    expect(candidateDetail(experience)).toBe("Lisbon · 2023-03 – Present");
  });

  it("returns null when there is nothing worth a second line", () => {
    expect(candidateDetail(item({ payload: { name: "Python" } }))).toBeNull();
  });
});

describe("datePrecisionNote", () => {
  it("warns when the document gave only a year", () => {
    const note = datePrecisionNote(
      item({ payload: { start_date: "2019-01-01", start_date_precision: "YEAR" } }),
    );

    // A year-only date is stored as 1 January, which is indistinguishable from
    // a real 1 January unless the user is told.
    expect(note).toMatch(/only a year/);
  });

  it("says nothing when the date was exact", () => {
    expect(
      datePrecisionNote(
        item({ payload: { start_date: "2019-03-15", start_date_precision: "DAY" } }),
      ),
    ).toBeNull();
  });
});

describe("readFlags", () => {
  it("returns validation flags so the review screen can warn", () => {
    expect(readFlags(item({ payload: { flags: ["UNSUPPORTED_NUMBERS"] } }))).toEqual([
      "UNSUPPORTED_NUMBERS",
    ]);
  });

  it("ignores anything that is not a known flag", () => {
    expect(readFlags(item({ payload: { flags: ["MADE_UP", 42] } }))).toEqual([]);
  });

  it("tolerates a missing flags key", () => {
    expect(readFlags(item())).toEqual([]);
  });
});

describe("editableFields", () => {
  it("offers the fields a person would correct", () => {
    expect(editableFields("EXPERIENCE")).toContain("company");
    expect(editableFields("EDUCATION")).toContain("institution");
  });

  it("never offers validation output as an editable field", () => {
    // `flags` and the precision markers describe what validation concluded, not
    // anything the user typed.
    for (const type of [
      "SKILL",
      "EXPERIENCE",
      "EXPERIENCE_ACHIEVEMENT",
      "PROJECT",
      "PROJECT_SKILL",
      "EDUCATION",
    ] as CandidateType[]) {
      expect(editableFields(type)).not.toContain("flags");
      expect(editableFields(type)).not.toContain("start_date_precision");
    }
  });
});

describe("grouping", () => {
  const experience = item({ id: "exp", candidate_type: "EXPERIENCE" });
  const achievement = item({
    id: "ach",
    candidate_type: "EXPERIENCE_ACHIEVEMENT",
    parent_item_id: "exp",
  });
  const skill = item({ id: "skill" });

  it("finds children of a parent", () => {
    expect(childrenOf([experience, achievement, skill], "exp")).toEqual([achievement]);
  });

  it("lists only top-level items of a type", () => {
    // Achievements must not appear as their own section — they are only
    // meaningful under the role they belong to.
    expect(topLevelOfType([experience, achievement, skill], "EXPERIENCE")).toEqual([experience]);
  });
});

describe("isDecided", () => {
  it("treats pending as undecided", () => {
    expect(isDecided(item())).toBe(false);
  });

  it.each(["ACCEPTED", "EDITED", "IGNORED"] as const)("treats %s as decided", (decision) => {
    expect(isDecided(item({ decision }))).toBe(true);
  });
});
