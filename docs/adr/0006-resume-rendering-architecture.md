# ADR-0006 — Resume rendering architecture

## Status

Accepted. Phase 7.

`docs/12-project-tracking.md` names resume-rendering architecture explicitly as
an example warranting an ADR, so this records the choice rather than leaving it
implicit in a dependency.

## Context

`docs/06-resume-engine.md` requires a rendered resume and separates content
from design:

```text
Structured Resume Content + Template = Rendered Resume
```

It also constrains the result: one page preferred and two allowed, an
ATS-friendly template first, and — pointedly — *do not solve overflow by
shrinking text to unreadable sizes*. Prefer shortening or removing low-value
content instead.

`docs/11-engineering-standards.md` adds one more: full resume text must never
be logged.

Three options were considered.

**A server-side PDF library** (WeasyPrint, ReportLab). Produces a real PDF on
the API host with no browser involved. WeasyPrint needs Pango, Cairo, and
GDK-PixBuf as system packages — a meaningful addition to the API image, and a
class of native-dependency failure the project has so far avoided entirely.
ReportLab needs the layout written imperatively, which is a lot of code for one
template.

**Headless Chromium** (Playwright). The best typography and true page control,
at the cost of a browser in the image and a process per render. For a
single-user MVP producing one page, that is a large amount of infrastructure
for the output.

**Server-rendered HTML with a print stylesheet**, exported by the browser the
user is already sitting in front of.

## Decision

**Render to HTML on the server, with a print stylesheet, and let the browser
produce the PDF.**

The API serves a complete, self-contained HTML document at
`GET /api/v1/resume-versions/{id}/render`. It carries `@page` rules, physical
units, and `print-color-adjust`, so the browser's own "Save as PDF" produces
the intended page. No new runtime dependency, and no native libraries in the
API image.

## Consequences

**Good.**

- Zero new dependencies. The renderer is a template and a stylesheet.
- Content and design stay separated exactly as `docs/06` asks: the HTML is
  generated from `ResumeSection` and `ResumeItem`, and the template decides
  nothing about what is on the page.
- ATS-friendly by construction. Semantic HTML with real headings and lists is
  the format parsers handle best; a PDF drawn by a layout library is often
  worse, because text order follows drawing order rather than reading order.
- The same document is the on-screen preview and the printed page, so what the
  user reviews is what they send.
- Testable without a browser. The output is a string, so tests assert on its
  content and its structure rather than on rendered pixels.

**Bad, and accepted.**

- **We do not control pagination.** Browsers differ slightly at page breaks.
  Mitigated by `break-inside: avoid` on each entry and by selection caps that
  keep the content near one page — which is `docs/06`'s own preferred remedy:
  select less rather than shrink text.
- **No server-side PDF bytes.** Nothing can email a PDF or attach one
  automatically. Phase 8's application tracker records *which version* was
  sent, not the file, so this does not block it. If a stored PDF is needed
  later, this decision is revisited with a new ADR — the HTML renderer remains
  the input to whatever produces it.
- **The user performs an extra step** (print → save as PDF). Acceptable for an
  MVP; a real cost to note rather than hide.

## Alternatives if this is revisited

Headless Chromium is the natural upgrade: it consumes the same HTML this
decision already produces, so switching is additive rather than a rewrite. That
is the main reason for choosing HTML as the intermediate form — every heavier
option takes HTML as its input.
