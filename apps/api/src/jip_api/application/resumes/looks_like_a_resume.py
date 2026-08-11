"""Is this document a resume at all?

DEV-020. Upload validation checks size, declared MIME type, extension and magic
bytes — four questions about *file integrity*, none about contents. A Hebrew
product specification was accepted, parsed, and presented as a normal review
screen with eleven skills and one project pulled out of the technology names
scattered through it. Nothing was invented; everything quoted real text. It was
simply not a resume.

The issue offered two fixes and this is the stricter one, chosen deliberately: a
soft warning is one more half-finished path, and a review screen the user is
told to ignore is a worse answer than a refusal.

**The risk that choice takes on.** DEV-020 says so plainly: rejection "is the
most likely to be wrong — an unusual or non-standard CV would be blocked, and
that is exactly the kind of heuristic that fails on the real case." Everything
below is shaped by that. The bar is not "does this look like a good resume". It
is "does this document show *any two* independent signs of being one", which a
one-page CV in either language clears without trying and a specification,
invoice or article does not.

Deliberately not used: a model call. Asking the parser whether the thing it is
about to parse is worth parsing costs the call this exists to save, and puts a
judgement we would have to explain behind an answer we could not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SELF_LABEL = re.compile(
    r"\b(curriculum\s+vitae|résumé|resume)\b|קורות\s*חיים",
    re.IGNORECASE,
)
"""The document naming itself. Rare in practice — most CVs lead with a name."""

_SECTION_HEADING = re.compile(
    r"\b(work\s+experience|professional\s+experience|employment(\s+history)?|experience"
    r"|education|qualifications|skills|technical\s+skills|projects|certifications"
    r"|publications|references)\b"
    r"|ניסיון(\s+תעסוקתי|\s+מקצועי)?|השכלה|כישורים|מיומנויות|פרויקטים|המלצות",
    re.IGNORECASE,
)
"""A section a resume has and a specification does not."""

_CONTACT = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]{2,}"  # an email address
    r"|(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{3,4}"  # a phone number
    r"|linkedin\.com/in/|github\.com/",
    re.IGNORECASE,
)
"""How to reach the person. A document about a product has no reason to carry
one, and a CV almost always does."""

_DATE_RANGE = re.compile(
    # The escapes are en dash and em dash. Written as escapes rather than
    # literals because a real resume separates its dates with one, and a
    # literal is indistinguishable from a plain hyphen at a glance.
    r"\b(19|20)\d{2}\s*[-\u2013\u2014]\s*((19|20)\d{2}|present|current|now|היום|כיום)\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(19|20)\d{2}\b"
    r"|\b(ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)\s+(19|20)\d{2}\b",
    re.IGNORECASE,
)
"""When something happened. A range or a month-and-year, not a bare year — a
bare year appears in every copyright notice ever written."""

_SIGNALS = {
    "a resume or CV heading": _SELF_LABEL,
    "a section like Experience, Education or Skills": _SECTION_HEADING,
    "contact details": _CONTACT,
    "dates for a role or a course of study": _DATE_RANGE,
}

MINIMUM_SIGNALS = 2
"""How many independent signals a document needs to be treated as a resume.

Two, and the number is the whole safety argument rather than a tuning knob.

A real CV carries three or four of these without trying: a heading, dates, and a
way to contact the author. Requiring two means a document has to be missing
*half* of what every resume has before it is refused, which leaves room for the
unusual ones — a one-page academic CV with no "Skills" section, a designer's
resume that is mostly links, a scan whose headings came through as images.

Requiring one would accept almost any document with an email address in it,
which is most documents. Requiring three would start refusing real CVs, and
DEV-020 is explicit that this is the failure mode that matters.
"""


@dataclass(frozen=True, slots=True)
class ResumeCheck:
    """What the document showed, and whether it was enough."""

    found: tuple[str, ...]
    is_resume: bool

    @property
    def reason(self) -> str:
        """Why it was refused, in terms the person who chose the file can act on.

        Names what was looked for rather than what was found. "We saw no dates"
        invites an argument about the dates that are there; "a resume normally
        has these" explains the judgement and points at the way out.
        """
        return (
            "This does not look like a resume. A resume normally has a section "
            "like Experience or Education, dates for each role, and contact "
            "details, and this document has almost none of that. If it really "
            "is your resume, add it to your profile by hand — nothing here is "
            "lost."
        )


def check(text: str) -> ResumeCheck:
    """Look for independent signs that ``text`` came from a resume.

    Counted by *kind*, not by number of matches: a document repeating one email
    address forty times has said one thing forty times, and forty is not more
    convincing than one.
    """
    found = tuple(name for name, pattern in _SIGNALS.items() if pattern.search(text))
    return ResumeCheck(found=found, is_resume=len(found) >= MINIMUM_SIGNALS)
