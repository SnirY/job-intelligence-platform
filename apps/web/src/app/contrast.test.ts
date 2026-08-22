import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every colour pairing the product actually renders, measured.
 *
 * `design-progress.md` has claimed since the palette landed that "every token
 * in both themes clears its floor". That was true of every pairing anybody
 * checked, and DEV-073 is what the gap looked like: `--foreground-faint` sat at
 * 3.05:1 in light while its own comment asserted it cleared 4.5, because the
 * dark twin passes at 9.61 and nobody had put *that* pair in front of the
 * arithmetic.
 *
 * So the claim becomes a test. The matrix below is the design decision written
 * down — which token is text, which is a rule, and which surface each one is
 * allowed to appear on. Adding a token without adding it here is the only way
 * back to an unmeasured pair, and that is a visible omission rather than a
 * silent one.
 *
 * Values are read from `globals.css` rather than duplicated, because two copies
 * of a colour drift and the copy in the test would be the one that lied.
 */

/* Two candidates because the suite is invoked from two directories: the
   workspace when `npm test --workspace @jip/web` runs it, the repo root when
   `run_checks.py` does. `import.meta.url` is not usable here — vitest serves
   this module through its own transform pipeline, where it is not a file: URL. */
const STYLESHEET = ["src/app/globals.css", "apps/web/src/app/globals.css"]
  .map((candidate) => join(process.cwd(), candidate))
  .find(existsSync);

if (!STYLESHEET) throw new Error("globals.css not found from " + process.cwd());

const CSS = readFileSync(STYLESHEET, "utf8");

/** WCAG floors. 4.5 for text below 18.66px bold / 24px regular; 3.0 otherwise. */
const TEXT = 4.5;
const NON_TEXT = 3.0;

type Theme = "light" | "dark";

/**
 * Token values per theme.
 *
 * `:root` carries light and the dark block overrides it, so dark is light with
 * replacements — exactly how the cascade resolves it at runtime.
 */
function readTokens(): Record<Theme, Record<string, string>> {
  const light: Record<string, string> = {};
  const dark: Record<string, string> = {};

  const darkStart = CSS.indexOf('[data-theme="dark"]');
  const lightSource = CSS.slice(0, darkStart === -1 ? undefined : darkStart);
  const darkSource = darkStart === -1 ? "" : CSS.slice(darkStart);

  const pattern = /--([a-z-]+):\s*(oklch\([^)]*\)|var\(--[a-z-]+\))/g;
  for (const match of lightSource.matchAll(pattern)) light[match[1] as string] = match[2] as string;
  for (const match of darkSource.matchAll(pattern)) dark[match[1] as string] = match[2] as string;

  return { light, dark: { ...light, ...dark } };
}

const TOKENS = readTokens();

function resolve(theme: Theme, name: string, seen = new Set<string>()): string {
  const value = TOKENS[theme][name];
  if (!value) throw new Error(`--${name} is not defined in ${theme}`);

  const alias = /^var\(--([a-z-]+)\)$/.exec(value);
  if (!alias) return value;

  if (seen.has(name)) throw new Error(`--${name} aliases itself`);
  seen.add(name);
  return resolve(theme, alias[1] as string, seen);
}

// --- oklch, and the sRGB luminance underneath it ------------------------------

function toSrgb(L: number, C: number, H: number): [number, number, number] {
  const h = (H * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);

  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;

  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];

  return linear.map((u) => {
    const clamped = Math.min(1, Math.max(0, u));
    return clamped > 0.0031308 ? 1.055 * clamped ** (1 / 2.4) - 0.055 : 12.92 * clamped;
  }) as [number, number, number];
}

function luminance(colour: string): number {
  const parsed = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(colour);
  if (!parsed) throw new Error(`cannot read ${colour}`);

  const [, L, C, H] = parsed;
  const [r, g, b] = toSrgb(Number(L), Number(C), Number(H));
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(theme: Theme, foreground: string, surface: string): number {
  const a = luminance(resolve(theme, foreground));
  const b = luminance(resolve(theme, surface));
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

// --- the matrix ---------------------------------------------------------------

/**
 * Tokens that carry words, and the surfaces they are set on.
 *
 * `--foreground-faint` is here rather than among the rules because that is what
 * it is used for — four files set provenance lines and band notes in it. The
 * whole of DEV-073 was that it had been reasoned about as if it were decoration.
 */
const TEXT_ON: Array<[string, string[]]> = [
  ["foreground", ["background", "card", "popover", "muted", "secondary", "accent"]],
  ["muted-foreground", ["background", "card", "popover", "muted"]],
  ["foreground-faint", ["background", "card"]],
  ["verdict-strong", ["background", "card"]],
  ["verdict-partial", ["background", "card"]],
  ["verdict-transfer", ["background", "card"]],
  ["verdict-gap", ["background", "card"]],
  ["verdict-blocked", ["background", "card"]],
  ["destructive", ["background", "card"]],
  ["success", ["background", "card"]],
];

/**
 * Labels written on a filled shape, which is a different question from the one
 * above and the one that was asked second. #42 shipped because only the first
 * had been.
 */
const LABEL_ON_FILL: Array<[string, string]> = [
  ["primary-foreground", "primary"],
  ["primary-foreground", "primary-hover"],
  ["destructive-foreground", "destructive"],
  ["success-foreground", "success"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["surface-raised-foreground", "surface-raised"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
];

/**
 * Shapes rather than words: focus rings, and fills whose *presence* is the
 * signal. 3.0 is the floor, and it is a floor rather than a target.
 */
const NON_TEXT_ON: Array<[string, string[]]> = [
  ["ring", ["background", "card"]],
  ["primary", ["background", "card"]],
  ["verdict-strong", ["card"]],
  ["verdict-partial", ["card"]],
  ["verdict-transfer", ["card"]],
  ["verdict-gap", ["card"]],
  ["verdict-blocked", ["card"]],
];

const THEMES: Theme[] = ["light", "dark"];

describe.each(THEMES)("%s theme", (theme) => {
  it.each(TEXT_ON.flatMap(([fg, surfaces]) => surfaces.map((bg) => [fg, bg] as const)))(
    "--%s reads as text on --%s",
    (foreground, surface) => {
      expect(ratio(theme, foreground, surface)).toBeGreaterThanOrEqual(TEXT);
    },
  );

  it.each(LABEL_ON_FILL)("--%s reads as a label on --%s", (foreground, fill) => {
    expect(ratio(theme, foreground, fill)).toBeGreaterThanOrEqual(TEXT);
  });

  it.each(NON_TEXT_ON.flatMap(([fg, surfaces]) => surfaces.map((bg) => [fg, bg] as const)))(
    "--%s is visible as a shape on --%s",
    (foreground, surface) => {
      expect(ratio(theme, foreground, surface)).toBeGreaterThanOrEqual(NON_TEXT);
    },
  );
});

describe("the matrix itself", () => {
  it("covers every token the stylesheet defines a colour for", () => {
    /* The failure this guards is the one DEV-073 actually was: not a pair that
       measured badly, but a pair nobody had put in front of the arithmetic. A
       token added without a row here would be unmeasured and nothing would
       say so. */
    const measured = new Set([
      ...TEXT_ON.map(([name]) => name),
      ...TEXT_ON.flatMap(([, surfaces]) => surfaces),
      ...LABEL_ON_FILL.flat(),
      ...NON_TEXT_ON.map(([name]) => name),
      ...NON_TEXT_ON.flatMap(([, surfaces]) => surfaces),
    ]);

    /* Deliberately outside the matrix, each for a stated reason rather than
       because nobody got to it. */
    const exempt = new Set([
      "border", // translucent in dark; measured against what shows through, which this cannot model
      "input", // same
      "notice", // only ever used at /40 and /5 opacity, never at full strength
      "primary-hover", // measured through the label pairing above
      "surface-raised", // measured through its own label pairing
      "radius", // not a colour
    ]);

    const defined = Object.keys(TOKENS.light).filter(
      (name) =>
        !name.startsWith("radius") &&
        !name.startsWith("font") &&
        // Tailwind's alias layer in `@theme inline`. Every one is `var(--x)` of
        // a token this matrix already measures, so checking them would be
        // measuring the same pair twice under a second name.
        !name.startsWith("color-"),
    );

    const unmeasured = defined.filter((name) => !measured.has(name) && !exempt.has(name));

    expect(unmeasured).toEqual([]);
  });
});
