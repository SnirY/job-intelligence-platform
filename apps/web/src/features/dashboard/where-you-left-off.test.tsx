import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WhereYouLeftOff } from "@/features/dashboard/resume-where-you-left-off";

/**
 * The opening line of the screen somebody opens without a task.
 *
 * What it must not do is imply the product knows when they were last here.
 * Nothing in the domain records that, so every "since your last visit" phrasing
 * is a fact being invented. This says when the thing happened; the reader
 * already knows whether that was before or after they looked.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function entry(overrides: Record<string, unknown> = {}) {
  return {
    at: new Date().toISOString(),
    kind: "JOB_SAVED",
    subject: "Staff Backend Engineer",
    job_id: "job-1",
    ...overrides,
  } as never;
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("where you left off", () => {
  it("says what was happening, as a sentence", async () => {
    vi.setSystemTime(new Date("2026-08-23T15:00:00"));

    render(<WhereYouLeftOff entry={entry({ at: "2026-08-22T14:00:00" })} />);

    expect(screen.getByRole("heading")).toHaveTextContent("Yesterday afternoon you were saving");
    expect(screen.getByText("Staff Backend Engineer")).toBeInTheDocument();
  });

  it("uses the vocabulary the feed actually emits", async () => {
    /* A first draft of the verb map named four events that do not exist —
       JOB_ANALYSED, JOB_MATCHED and two more — so every application row would
       have fallen through to the default while looking deliberate. The feed
       emits JOB_SAVED and the six ApplicationEvent types. */
    vi.setSystemTime(new Date("2026-08-23T15:00:00"));

    render(<WhereYouLeftOff entry={entry({ kind: "SUBMITTED", at: "2026-08-23T09:00:00" })} />);

    expect(screen.getByRole("heading")).toHaveTextContent("This morning you were sending");
  });

  it("falls back to something true rather than something wrong", async () => {
    // A kind this build does not know is still a real thing somebody did.
    vi.setSystemTime(new Date("2026-08-23T15:00:00"));

    render(<WhereYouLeftOff entry={entry({ kind: "SOMETHING_NEW" })} />);

    expect(screen.getByRole("heading")).toHaveTextContent("you were working on");
  });

  it("drops the time of day once it stops being a memory", async () => {
    /* "Three weeks ago in the afternoon" is precision nobody asked for about a
       thing they have forgotten. */
    vi.setSystemTime(new Date("2026-08-23T15:00:00"));

    render(<WhereYouLeftOff entry={entry({ at: "2026-07-01T14:00:00" })} />);

    expect(screen.getByRole("heading")).not.toHaveTextContent(/afternoon/);
  });

  it("says nothing at all when nothing has happened", async () => {
    // Day one. An opening line about a thread nobody has put down would be the
    // screen greeting a return that never happened.
    const { container } = render(<WhereYouLeftOff entry={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("offers no way back when there is nowhere to go", async () => {
    // An application event with no job behind it. A link to nothing is worse
    // than no link.
    vi.setSystemTime(new Date("2026-08-23T15:00:00"));

    render(<WhereYouLeftOff entry={entry({ job_id: null, subject: "An application" })} />);

    expect(screen.queryByRole("link", { name: "Pick it back up" })).not.toBeInTheDocument();
  });
});
