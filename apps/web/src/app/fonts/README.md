# Vendored typefaces

`woff2` files committed to the repo rather than fetched at build time, because
`next build` runs on a network-restricted runner and a webfont fetch fails
there. That was the reason the product ran on the system font stack; see the
front-end audit of 2026-08-11, finding F27.

Extracted from Fontsource, then the packages were removed — nothing imports
them, and a dependency that exists only to be copied out of is a dependency
somebody will later try to import.

| File | Source package | Version | Subset |
|---|---|---|---|
| `manrope-latin-wght-normal.woff2` | `@fontsource-variable/manrope` | 5.3.0 | latin |
| `manrope-latin-ext-wght-normal.woff2` | `@fontsource-variable/manrope` | 5.3.0 | latin-ext |
| `heebo-hebrew-wght-normal.woff2` | `@fontsource-variable/heebo` | 5.3.0 | hebrew |
| `ibm-plex-mono-latin-400-normal.woff2` | `@fontsource/ibm-plex-mono` | 5.3.0 | latin, 400 |
| `ibm-plex-mono-latin-500-normal.woff2` | `@fontsource/ibm-plex-mono` | 5.3.0 | latin, 500 |

All three families are SIL Open Font License 1.1, which permits redistribution
inside a larger work and does not require attribution in the interface.

## Replacing or adding a subset

```bash
npm install --no-save @fontsource-variable/manrope
cp node_modules/@fontsource-variable/manrope/files/manrope-<subset>-wght-normal.woff2 apps/web/src/app/fonts/
npm uninstall @fontsource-variable/manrope
```

Then declare the file in `../fonts.ts`. A new subset is a new `localFont()` call
with `preload: false`, appended to the family list in `globals.css` — coverage
is per-glyph, so the browser falls through the list character by character and
only downloads a file when the page contains something that needs it.
