"""Reading values out of somebody else's JSON.

Three helpers, and all three exist for the same reason: a board is an untrusted
document. A field documented as a string arrives as `null`, as a number, as an
object; a date arrives in three formats across three providers. Code that reads
these inline ends up either trusting them — and raising on a posting that was
merely odd — or repeating the same four checks in every provider.

Nothing here guesses. A value that cannot be read is `None`, which every caller
already has to handle, rather than a default that would read as a fact.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

MAX_EPOCH_SECONDS = 4_102_444_800
"""1 January 2100, as seconds.

Used only to tell seconds from milliseconds: Lever sends epoch milliseconds and
nothing else here does, and a value above this is milliseconds rather than a
posting from the far future.
"""


def as_text(value: Any) -> str | None:
    """A non-empty trimmed string, or ``None``.

    Numbers are not coerced. A title that arrived as `12` is a board doing
    something unexpected, and rendering "12" as a job title would hide that.
    """
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def iso_datetime(value: Any) -> dt.datetime | None:
    """An ISO-8601 timestamp, always timezone-aware.

    Both Greenhouse and Ashby send an offset, so a naive result means the format
    changed. It is treated as UTC rather than discarded — the date is still
    approximately right, and losing "posted three weeks ago" over a missing `Z`
    would be the wrong trade.
    """
    text = as_text(value)
    if text is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def epoch_datetime(value: Any) -> dt.datetime | None:
    """An epoch timestamp in seconds or milliseconds, as UTC.

    Lever sends milliseconds. The unit is not stated in the payload, so it is
    inferred from magnitude — see `MAX_EPOCH_SECONDS`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = value / 1000 if abs(value) > MAX_EPOCH_SECONDS else float(value)
    try:
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None
