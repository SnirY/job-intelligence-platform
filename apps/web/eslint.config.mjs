import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

/*
 * Colour belongs to `globals.css`, and nowhere else.
 *
 * Every surface in this app reads a semantic token — `bg-card`,
 * `text-muted-foreground`, `--verdict-gap` — and that indirection is what made
 * the visual language swappable in a single file: the Porcelain palette
 * replaced the previous one with 338 tests passing unchanged, because nothing
 * outside the stylesheet knew what colour anything was.
 *
 * The property is worth exactly as much as it is enforced. It survives until
 * the first `#2447E6` written into a component, and then one screen quietly
 * stops following the palette — noticed a redesign later, when a single card
 * comes out the wrong colour and nobody remembers why.
 *
 * Three things are caught: hex literals, colour functions, and Tailwind's own
 * palette classes. The last are the easiest to write by accident and the worst
 * to keep, because `text-amber-600` does not follow the theme — it stays amber
 * in dark mode and in every palette that comes after this one.
 *
 * Scoped to the feature and component trees. The stylesheet is where raw values
 * are meant to live, and it is not JavaScript.
 *
 * One gap, stated rather than papered over: a class assembled by interpolation
 * — `border-${shade}-500` — splits across template elements and is not caught.
 * Nothing in this codebase builds a colour that way, and a rule that catches
 * the three shapes people actually write is worth more than one that tries to
 * catch every shape and fires on innocent strings instead.
 */
const PALETTE = [
  "slate",
  "gray",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
].join("|");

const UTILITY =
  "bg|text|border|ring|fill|stroke|from|via|to|outline|decoration|shadow|accent|caret|divide|placeholder";

const HEX = "#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})";
// `[(]` rather than an escaped paren: esquery strips the backslash out of a
// selector's regex before handing it to RegExp, so the group never closes.
const COLOUR_FN = "(?:oklch|rgba?|hsla?)[(]";
const PALETTE_CLASS = `(?:${UTILITY})-(?:${PALETTE})-[0-9]{2,3}`;

const TOKEN_ADVICE =
  "Colour lives in globals.css. Use a semantic token — bg-card, text-muted-foreground, text-verdict-gap. If none of them fits, the missing thing is the token.";

/** Both node types, because a class string is as often interpolated as literal. */
const forbid = (pattern, message) => [
  { selector: `Literal[value=/${pattern}/]`, message },
  { selector: `TemplateElement[value.raw=/${pattern}/]`, message },
];

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // Unused values are usually a mistake; an underscore prefix marks the
      // deliberate exceptions.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    files: ["src/features/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...forbid(HEX, `Raw hex colour. ${TOKEN_ADVICE}`),
        ...forbid(COLOUR_FN, `Raw colour function. ${TOKEN_ADVICE}`),
        ...forbid(
          PALETTE_CLASS,
          `Tailwind palette colour — these bypass the token layer and do not follow the theme. ${TOKEN_ADVICE}`,
        ),
      ],
    },
  },
  {
    ignores: ["node_modules/**", ".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts"],
  },
];

export default eslintConfig;
