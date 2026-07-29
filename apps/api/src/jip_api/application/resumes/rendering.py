"""Rendering a resume version to a printable HTML document.

See ADR-0006 for why HTML rather than a server-side PDF library. In short: no
native dependencies, semantic markup is what ATS parsers handle best, and every
heavier option takes HTML as its input anyway.

``docs/06-resume-engine.md`` separates content from design, so this module owns
the design and nothing else. It reads sections and items and decides only how
they look — it never selects, reorders, or edits. What is on the page was
decided before it was called.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jip_api.application.resumes.authoring import load_content
from jip_api.domain.career.models import CareerProfile
from jip_api.domain.resumes.models import ResumeItem, ResumeSectionKind, ResumeVersion

SECTION_TITLES = {
    ResumeSectionKind.SUMMARY: "Summary",
    ResumeSectionKind.SKILLS: "Skills",
    ResumeSectionKind.EXPERIENCE: "Experience",
    ResumeSectionKind.PROJECTS: "Projects",
    ResumeSectionKind.EDUCATION: "Education",
    ResumeSectionKind.CERTIFICATIONS: "Certifications",
    ResumeSectionKind.OTHER: "Other",
}


@dataclass(frozen=True, slots=True)
class RenderedResume:
    """A complete, self-contained HTML document."""

    html: str
    filename: str


# One page preferred, two allowed (docs/06). The stylesheet uses physical units
# and real page rules so the browser's own PDF export produces the intended
# result rather than a screenshot of a web page.
#
# Deliberately not shrinking anything to fit: docs/06 forbids solving overflow
# by making text unreadable, so the type sizes here are fixed and it is
# selection's job to fit the content.
_STYLE = """
@page { size: A4; margin: 14mm 16mm; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 10.5pt;
  line-height: 1.42;
  color: #111;
  background: #fff;
}
.sheet { max-width: 178mm; margin: 0 auto; padding: 8mm 0; }
header { border-bottom: 1.5pt solid #111; padding-bottom: 6pt; margin-bottom: 10pt; }
h1 { font-size: 19pt; margin: 0 0 2pt; letter-spacing: 0.2pt; }
.headline { font-size: 11pt; color: #333; margin: 0; }
.contact { font-size: 9pt; color: #444; margin: 4pt 0 0; }
h2 {
  font-size: 10.5pt; text-transform: uppercase; letter-spacing: 0.9pt;
  border-bottom: 0.5pt solid #999; padding-bottom: 2pt;
  margin: 12pt 0 6pt;
}
.entry { margin-bottom: 7pt; break-inside: avoid; page-break-inside: avoid; }
.entry-heading { font-weight: bold; font-size: 10.5pt; margin: 0 0 1pt; }
ul { margin: 2pt 0 0; padding-left: 14pt; }
li { margin-bottom: 2pt; }
p { margin: 0 0 3pt; }
.skills { margin: 0; }
section { break-inside: auto; }
h2 { break-after: avoid; page-break-after: avoid; }
@media screen {
  body { background: #f4f4f5; padding: 24px 12px; }
  .sheet { background: #fff; padding: 16mm; box-shadow: 0 1px 4px rgba(0,0,0,.15); }
  .print-hint {
    max-width: 178mm; margin: 0 auto 12px; font-family: system-ui, sans-serif;
    font-size: 13px; color: #444;
  }
}
@media print { .print-hint { display: none; } }
"""


def render_version(
    session: Session, version: ResumeVersion, *, profile: CareerProfile | None = None
) -> RenderedResume:
    """Turn a version's stored content into a printable document.

    Everything is escaped. The text came from the user and from model output
    they approved, and neither is trusted as markup — a resume bullet
    containing a script tag would otherwise execute on our origin.
    """
    sections = load_content(session, version.id)

    name = _profile_name(profile)
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{html.escape(name or 'Resume')}</title>",
        f"<style>{_STYLE}</style></head><body>",
        '<p class="print-hint">Use your browser&rsquo;s Print &rarr; Save as PDF '
        "to export this.</p>",
        '<div class="sheet">',
    ]

    parts.append("<header>")
    parts.append(f"<h1>{html.escape(name or 'Resume')}</h1>")
    if profile and profile.headline:
        parts.append(f'<p class="headline">{html.escape(profile.headline)}</p>')
    contact = _contact_line(profile)
    if contact:
        parts.append(f'<p class="contact">{html.escape(contact)}</p>')
    parts.append("</header>")

    for section, items in sections:
        if not items:
            continue
        kind = ResumeSectionKind(section.kind)
        if kind is ResumeSectionKind.HEADER:
            # The header is rendered from the profile above; a HEADER section's
            # items would duplicate it.
            continue

        title = section.title or SECTION_TITLES.get(kind, kind.value.title())
        parts.append("<section>")
        parts.append(f"<h2>{html.escape(title)}</h2>")

        if kind is ResumeSectionKind.SKILLS:
            # One line, comma separated. A bulleted list of fourteen single
            # words wastes most of a page for no gain.
            parts.append(
                '<p class="skills">' + html.escape(", ".join(item.text for item in items)) + "</p>"
            )
        else:
            grouped = _group_by_heading(items)
            for heading, texts in grouped:
                parts.append('<div class="entry">')
                if heading:
                    parts.append(f'<p class="entry-heading">{html.escape(heading)}</p>')
                if len(texts) == 1 and not heading:
                    parts.append(f"<p>{html.escape(texts[0])}</p>")
                else:
                    parts.append("<ul>")
                    parts.extend(f"<li>{html.escape(text)}</li>" for text in texts)
                    parts.append("</ul>")
                parts.append("</div>")

        parts.append("</section>")

    parts.append("</div></body></html>")

    return RenderedResume(html="".join(parts), filename=_filename(name, version))


def _group_by_heading(items: list[ResumeItem]) -> list[tuple[str | None, list[str]]]:
    """Collapse consecutive items that share a heading into one entry.

    Four bullets from the same role belong under one job title, not four
    repetitions of it. Consecutive rather than global, so the display order the
    user chose is preserved.
    """
    grouped: list[tuple[str | None, list[str]]] = []
    for item in items:
        heading = item.heading
        if grouped and grouped[-1][0] == heading:
            grouped[-1][1].append(item.text)
        else:
            grouped.append((heading, [item.text]))
    return grouped


def _profile_name(profile: CareerProfile | None) -> str:
    """The name on the page.

    ``CareerProfile`` has no name column — identity lives with the auth
    provider (ADR-0005), and the profile deliberately does not duplicate it. So
    the headline stands in until the user supplies something better, rather
    than the renderer inventing a placeholder.
    """
    if profile and profile.headline:
        return profile.headline
    return "Resume"


def _contact_line(profile: CareerProfile | None) -> str:
    if profile is None:
        return ""
    parts: list[str] = []
    if profile.current_location:
        parts.append(profile.current_location)
    for link in profile.links or []:
        url = link.get("url") if isinstance(link, dict) else None
        if url:
            parts.append(str(url))
    return " · ".join(parts)


def _filename(name: str, version: ResumeVersion) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in name).strip("-").lower() or "resume"
    return f"{safe}-v{version.version}.html"


def render_filename_for(version_id: uuid.UUID) -> str:  # pragma: no cover - convenience
    return f"resume-{version_id}.html"
