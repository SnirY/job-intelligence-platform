import localFont from "next/font/local";

/*
 * Self-hosted typefaces. D10 ("Porcelain") specifies Manrope for the interface
 * and IBM Plex Mono for figures.
 *
 * Local rather than `next/font/google` because a webfont fetch at build time
 * makes `next build` fail on a network-restricted runner. That constraint was
 * the reason the product shipped on the system font stack, and it is a build
 * constraint rather than a design one — vendoring the `woff2` files removes it
 * without giving up the typeface. See `fonts/README.md` for provenance.
 *
 * Four faces rather than two, because coverage is per-glyph: a font family list
 * is searched in order for each character, so a glyph missing from Manrope's
 * latin subset falls through to the next family rather than to the OS. Only the
 * two faces that render an English screen are preloaded; the browser fetches
 * the others when a page actually contains a character that needs them.
 */

/*
 * ORDERING RULES. Two of them, pulling in opposite directions, and the
 * arrangement below is the only one that satisfies both.
 *
 * 1. Only the last family in a chain may carry fallbacks. `next/font` appends
 *    two things to each variable: the `fallback` list, and a metric-adjusted
 *    `local()` face that prevents layout shift. Both are real families with
 *    broad coverage, so a face carrying them swallows every glyph behind it.
 *    Left on Manrope, the chain would read
 *
 *        Manrope, Manrope_Fallback (local Arial), system-ui, Heebo
 *
 *    and Hebrew would render in Arial, because Heebo sits behind two families
 *    that both have Hebrew glyphs.
 *
 * 2. Manrope has to come *first*, which rules out simply putting it last. The
 *    subsets are not disjoint: every one of these files also carries the shared
 *    punctuation. Measured at 100px, Heebo's space is 24% wider than Manrope's
 *    and its hyphen 34% narrower, so a chain led by Heebo sets English text
 *    with Hebrew word-spacing and prints "Full-time" with a foreign hyphen —
 *    wrong in a way that is visible but hard to attribute.
 *
 * The resolution is to end the chain on the latin-ext subset. It is the same
 * typeface, so the metric-adjusted fallback computed from it is the one Manrope
 * wanted anyway, and the glyphs it holds are ones no earlier face has. Manrope
 * and Heebo are declared bare so they capture only what they genuinely cover.
 *
 * Verified by measurement rather than by reading: Manrope covers `S`, `7`,
 * space and hyphen; Heebo alone covers `א`; only the ext subset covers `Ł`.
 *
 * The bare options are repeated per call rather than shared through a constant
 * because `next/font` reads these arguments at compile time and rejects a
 * spread: "Unexpected spread".
 */

/*
 * Hebrew. Manrope has no Hebrew glyphs, and the audit of 2026-08-11 named this
 * as the expensive half of having no typeface: every OS serves a different
 * Hebrew face at a different x-height, so the product looks like a different
 * product per machine — including in screenshots.
 *
 * Present before the interface is translated on purpose. Job postings and
 * resumes are user content and may already be Hebrew inside an English
 * interface, and that text has to render in something we chose.
 */
/* The interface face, and the head of the chain. Bare, so that the punctuation
   it shares with the other subsets resolves here. */
const manrope = localFont({
  src: "./fonts/manrope-latin-wght-normal.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-manrope",
  adjustFontFallback: false,
});

const heebo = localFont({
  src: "./fonts/heebo-hebrew-wght-normal.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-heebo",
  preload: false,
  adjustFontFallback: false,
});

/*
 * Accented Latin — European company and place names, which are product data —
 * and the end of the chain, so this is the face that carries the fallbacks for
 * everything ahead of it. Manrope's own metrics, since it is Manrope.
 */
const manropeExt = localFont({
  src: "./fonts/manrope-latin-ext-wght-normal.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-manrope-ext",
  preload: false,
  fallback: ["system-ui", "sans-serif"],
});

/*
 * Figures. Two static weights rather than a variable axis: IBM Plex Mono ships
 * no variable build, and D10 uses exactly 400 and 500.
 *
 * Monospace here is for alignment, not for the look of code — a column of
 * scores has to line up, which is also why `tabular-nums` stays on the score.
 */
const plexMono = localFont({
  src: [
    { path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500", style: "normal" },
  ],
  display: "swap",
  variable: "--font-plex-mono",
  fallback: ["ui-monospace", "monospace"],
});

/**
 * The class that publishes every font variable to the document. Goes on `<html>`
 * so that portalled content — dialogs, the mobile drawer, Clerk's widgets —
 * inherits it too; `globals.css` composes these variables into `--font-sans`
 * and `--font-mono`, which is what components actually reference.
 */
export const fontVariables = [
  manrope.variable,
  heebo.variable,
  manropeExt.variable,
  plexMono.variable,
].join(" ");
