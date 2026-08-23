"""Enums the API sends, and the TypeScript that claims to describe them.

Written after `JobImportMethod.DISCOVERED` was added to the Python enum in #86
and never mirrored in `packages/shared-types`. Nothing failed: the TypeScript
union simply did not know the member existed, `Record<JobImportMethod, string>`
was exhaustive over a union that was already wrong, and `tsc` was satisfied.

What it cost was a blank badge. The API sent `DISCOVERED`, the label lookup
returned `undefined`, and every job found by a board scan rendered with an empty
tag where its origin should have been — which is the one thing that badge exists
to say.

**This reads the TypeScript as text on purpose.** A generated client would be
the thorough answer and is a much larger change; this is the cheap guard that
would have caught the actual defect, and it fails loudly the next time an enum
grows on one side only.
"""

from __future__ import annotations

import enum
from pathlib import Path

import pytest

from jip_api.domain.applications.models import ApplicationSource, ApplicationStatus
from jip_api.domain.jobs.models import JobImportMethod, JobProcessingStatus, WorkMode
from jip_api.domain.resumes.cover_letters import CoverLetterStatus

SHARED_TYPES = Path(__file__).resolve().parents[4] / "packages" / "shared-types" / "src"


def _sources() -> str:
    """Every contract file, concatenated.

    Concatenated rather than checked per file because which file an enum lives
    in is a housekeeping decision, and a test that pinned it would fail on a
    move that broke nothing.
    """
    assert SHARED_TYPES.is_dir(), f"shared-types not found at {SHARED_TYPES}"
    return "\n".join(path.read_text(encoding="utf-8") for path in SHARED_TYPES.glob("*.ts"))


@pytest.mark.parametrize(
    "enum_type",
    [
        JobImportMethod,
        JobProcessingStatus,
        WorkMode,
        ApplicationStatus,
        ApplicationSource,
        CoverLetterStatus,
    ],
    ids=lambda e: e.__name__,
)
def test_every_member_the_api_can_send_is_in_the_contract(enum_type: type[enum.StrEnum]) -> None:
    """A member the frontend has never heard of arrives as an unhandled string.

    Sometimes that is a blank label, sometimes a missing branch. Either way the
    screen says less than it knows, which is the defect class this whole suite
    keeps finding.
    """
    contract = _sources()
    missing = [member.value for member in enum_type if f'"{member.value}"' not in contract]

    assert not missing, (
        f"{enum_type.__name__} has members the TypeScript contract does not name: "
        f"{missing}. Add them to packages/shared-types/src, including any "
        f"Record<> that maps the union to labels."
    )


def test_the_import_method_labels_cover_every_member() -> None:
    """The specific lookup that returned `undefined` and rendered nothing.

    Checked separately because the test above only proves the *value* appears
    somewhere in the contract — a union could name it while the label map does
    not, which is the same blank badge by a different route.
    """
    labels = _sources().split("IMPORT_METHOD_LABELS")[1].split("};")[0]
    missing = [member.value for member in JobImportMethod if f"{member.value}:" not in labels]

    assert not missing, f"IMPORT_METHOD_LABELS has no label for: {missing}"
