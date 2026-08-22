import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GapMatrix } from "@/features/insights/gap-matrix";

/**
 * The fourth MVP visualisation, and the question a ranking cannot hold.
 *
 * The gaps list beside this is ordered worst-first. That answers "what is the
 * worst" and puts a gap named once as essential in the same column as one named
 * twelve times as a preference — two different problems, one order.
 */

function gap(overrides: Record<string, unknown> = {}) {
  return {
    key: "kubernetes",
    skill_id: "skill-1",
    name: "Kubernetes",
    catalogued: true,
    jobs: 6,
    share: 25,
    importance: { PREFERRED: 6 },
    role_families: {},
    state: "MISSING",
    held: false,
    ...overrides,
  } as never;
}

describe("the gap matrix", () => {
  it("places a gap by how often it was asked and how firmly", async () => {
    render(
      <GapMatrix gaps={[gap({ jobs: 9, importance: { CORE: 1, PREFERRED: 8 } })]} analysed={12} />,
    );

    /* Firmest, not most common. One posting calling something essential is the
       fact that decides whether the gap can block an application, and an
       average would bury exactly that — eight preferences do not soften one
       requirement. */
    expect(
      screen.getByRole("button", { name: /Kubernetes .* at its firmest Essential/ }),
    ).toBeInTheDocument();
  });

  it("says both axes in the name, not only in the position", async () => {
    // A position says nothing to somebody who cannot see it.
    render(<GapMatrix gaps={[gap()]} analysed={24} />);

    expect(screen.getByRole("button", { name: /Kubernetes/ })).toHaveAccessibleName(
      "Kubernetes — asked for by 6 of 24 jobs, at its firmest Preferred",
    );
  });

  it("keeps every quadrant, including the empty ones", async () => {
    /* The same rule the requirement field keeps. An empty "often, and
       mandatory" square is the best news this chart can deliver, and hiding it
       removes the one whose emptiness is the message. */
    render(<GapMatrix gaps={[gap()]} analysed={24} />);

    for (const note of [
      /Asked for often, and worded as mandatory/,
      /Asked for rarely, and worded as mandatory/,
      /Asked for often, and as a preference/,
      /Asked for rarely, and as a preference/,
    ]) {
      expect(screen.getByText(note)).toBeInTheDocument();
    }
  });

  it("reads often as a share of what was analysed, not a fixed count", async () => {
    /* Ten postings out of twelve is a pattern; ten out of two hundred is not,
       and a threshold in absolute numbers would call both the same thing. */
    const { rerender } = render(<GapMatrix gaps={[gap({ jobs: 10 })]} analysed={12} />);

    const often = screen.getByText(/Asked for often, and as a preference/).closest("div");
    expect(
      within(often as HTMLElement).getByRole("button", { name: /Kubernetes/ }),
    ).toBeInTheDocument();

    rerender(<GapMatrix gaps={[gap({ jobs: 10 })]} analysed={200} />);

    const rare = screen.getByText(/Asked for rarely, and as a preference/).closest("div");
    expect(
      within(rare as HTMLElement).getByRole("button", { name: /Kubernetes/ }),
    ).toBeInTheDocument();
  });

  it("names every gap in the table, which the plot does not", async () => {
    // docs/08-ui-ux.md asks every chart for a textual alternative, and the
    // recorded rule is that no label lives only on hover.
    render(<GapMatrix gaps={[gap()]} analysed={24} />);

    await userEvent.click(screen.getByRole("button", { name: "Table" }));

    const row = screen.getByRole("row", { name: /Kubernetes/ });
    expect(within(row).getByText("6 of 24")).toBeInTheDocument();
    expect(within(row).getByText("Preferred")).toBeInTheDocument();
  });

  it("says what a selection means rather than leaving it to the square", async () => {
    render(<GapMatrix gaps={[gap()]} analysed={24} />);

    expect(screen.getByText(/Pick a gap to see/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Kubernetes/ }));

    expect(screen.getByText(/Asked for by/)).toHaveTextContent(
      "Asked for by 6 of 24 analysed jobs. At its firmest, worded as preferred.",
    );
  });

  it("says when a gap cannot be added from here", async () => {
    /* Rather than leaving it to the absence of a link. A name the catalogue
       does not hold cannot reach a profile, and a reader is entitled to know
       that is why. */
    render(<GapMatrix gaps={[gap({ catalogued: false })]} analysed={24} />);
    await userEvent.click(screen.getByRole("button", { name: /Kubernetes/ }));

    expect(screen.getByText(/not in the skill catalogue yet/)).toBeInTheDocument();
  });

  it("draws nothing when there is nothing missing", async () => {
    const { container } = render(<GapMatrix gaps={[]} analysed={24} />);

    expect(container).toBeEmptyDOMElement();
  });
});
