"""No ``extra=`` key may collide with a reserved ``LogRecord`` attribute.

Found the hard way on 2026-07-31, in the browser, on the first real resume
import: confirming the review returned 500 and the screen said "Nothing was
changed". It was right — nothing had been.

The cause was one word. ``confirm_extraction`` logged
``extra={"created": result.created_count}``, and ``created`` is the
``LogRecord`` field holding the record's own timestamp. ``logging.makeRecord``
refuses to overwrite it:

```python
raise KeyError("Attempt to overwrite %r in LogRecord" % key)
```

That `KeyError` propagated out of the log call, out of the use case, and past
the route's ``session.commit()`` — so **a logging statement destroyed the
operation it existed to describe**, and did it only on the success path, after
every record had been applied.

Nothing catches this except execution. It is not a type error, the key is a
plain string, and the collision depends on a list inside the standard library.
So this walks the source instead: cheap, total, and it fails at the moment
someone writes the next one rather than the moment a user does.
"""

from __future__ import annotations

import ast
import logging
import pathlib

SOURCE_ROOTS = [
    pathlib.Path(__file__).resolve().parents[2] / "src",
    pathlib.Path(__file__).resolve().parents[4] / "apps" / "worker" / "src",
    pathlib.Path(__file__).resolve().parents[4] / "packages",
]

RESERVED: frozenset[str] = frozenset(
    set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
    # makeRecord rejects these two by name as well as by presence.
    | {"message", "asctime"}
)
"""Derived from a real ``LogRecord`` rather than hardcoded.

A literal list would drift the first time Python adds a field — 3.12 added
``taskName``, which is exactly the kind of addition that would turn a passing
suite into a production 500.
"""


def _extra_keys() -> list[tuple[pathlib.Path, int, str]]:
    """Every literal key passed to an ``extra=`` dict in the codebase."""
    found: list[tuple[pathlib.Path, int, str]] = []

    for root in SOURCE_ROOTS:
        if not root.exists():  # pragma: no cover - layout differs per checkout
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                        continue
                    for key in keyword.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            found.append((path, key.lineno, key.value))
    return found


def test_no_logging_extra_key_shadows_a_record_attribute() -> None:
    collisions = [
        f"{path.name}:{line} uses extra key {key!r}"
        for path, line, key in _extra_keys()
        if key in RESERVED
    ]

    assert not collisions, (
        "These would raise KeyError at runtime and abort whatever was logging them:\n  "
        + "\n  ".join(collisions)
    )


def test_the_scan_actually_finds_something() -> None:
    """Guards the guard.

    A walk that silently matches nothing would pass forever and protect
    nothing — the shape this repository has already been bitten by twice.
    """
    assert len(_extra_keys()) > 20


def test_the_reserved_set_is_derived_not_guessed() -> None:
    """If this ever shrinks to a hand-written list, the drift starts."""
    assert "created" in RESERVED
    assert "message" in RESERVED
    assert "filename" in RESERVED
    # Added in 3.12. Present only because the set is read from a real record.
    assert "taskName" in RESERVED
