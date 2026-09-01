"""where a document's text came from

Phase 14, slice 2. Slice 1 taught the extractor to read a scan when the file
had no text layer, and the pipeline logged which of the two paths ran. Logging
it is enough to debug with and not enough to show anybody: the screen where a
person confirms what a model found in their resume could not say whether that
text was read from the file or guessed from a picture of it.

Two columns, both nullable, and the nullability is the interesting part.

`text_source` is null for every row written before this migration. It is
tempting to backfill them to `TEXT_LAYER`, since OCR did not exist when they
were written and therefore every one of them came from a text layer. That
reasoning is sound and the backfill would still be wrong: null here means *not
extracted yet*, and writing a value nobody checked turns an absence into a
claim. `docs/08-ui-ux.md` makes the same argument about dates.

`ocr_confidence` is null whenever the text came from a text layer, rather than
100. A text layer has no confidence; it is not confidence of one hundred. Any
query that later asks "show me the documents we were unsure about" gets a
different and correct answer because of that distinction.

Stored as VARCHAR through `StrEnumType` rather than a PostgreSQL enum, which is
this codebase's standing choice: adding a member to the Python enum then needs
no migration at all.

Revision ID: a1e4c907b3d2
Revises: c3f8b5d29a41
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1e4c907b3d2"
down_revision: str | None = "c3f8b5d29a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("text_source", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
    )
    # A confidence outside 0-100 is not a low reading, it is a bug in whatever
    # wrote it — a unit mix-up, or a fraction where a percentage was meant.
    # Cheaper to refuse at the boundary than to find later in a figure shown to
    # a user as if it meant something.
    op.create_check_constraint(
        "ocr_confidence_range",
        "source_documents",
        "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint("ocr_confidence_range", "source_documents", type_="check")
    op.drop_column("source_documents", "ocr_confidence")
    op.drop_column("source_documents", "text_source")
