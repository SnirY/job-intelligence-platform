import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * jsdom implements no media queries at all, and `window.matchMedia` is simply
 * absent rather than returning a default. `next-themes` calls it to read
 * `prefers-color-scheme`, so every test that renders the application shell
 * would throw on a function that does not exist.
 *
 * Stubbed here rather than per file because the theme provider wraps the whole
 * app: any test mounting a screen inherits it, and a per-file stub is a list
 * someone has to keep adding to.
 *
 * It reports "does not match", which makes the system preference light. Tests
 * that care about a specific theme set it explicitly rather than relying on
 * this, so the value is a default and not an assumption.
 */
/**
 * The guard is for the files that opt out of jsdom with
 * `// @vitest-environment node` (DEV-058): `setupFiles` runs for every test
 * file regardless of its environment, so an unguarded `window` here is a
 * ReferenceError that fails the whole file before a single test runs.
 */
const hasDom = typeof window !== "undefined";

if (hasDom && !window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

afterEach(() => {
  if (hasDom) cleanup();
});
