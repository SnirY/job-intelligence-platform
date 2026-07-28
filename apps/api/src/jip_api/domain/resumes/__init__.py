"""Resumes domain.

A resume is a selected representation of the career profile, never a second
copy of it. Nothing in this package stores a career fact — items hold the words
that appear on a page plus a pointer to the row they came from.
"""

from jip_api.domain.resumes.models import (
    Resume,
    ResumeFamily,
    ResumeItem,
    ResumeItemSource,
    ResumeSection,
    ResumeSectionKind,
    ResumeVersion,
    ResumeVersionStatus,
)

__all__ = [
    "Resume",
    "ResumeFamily",
    "ResumeItem",
    "ResumeItemSource",
    "ResumeSection",
    "ResumeSectionKind",
    "ResumeVersion",
    "ResumeVersionStatus",
]
