"""Errors raised by the application layer.

These are transport-agnostic on purpose — the application layer must not import
FastAPI (``docs/11-engineering-standards.md``). The API layer maps them onto the
error envelope.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for expected failures in a use case."""


class ResourceNotFoundError(ApplicationError):
    """The resource does not exist, or does not belong to this user.

    Deliberately the same error for both. Distinguishing "not yours" from "does
    not exist" would let a caller enumerate which ids other users own.
    """


class DuplicateResourceError(ApplicationError):
    """Creating or renaming this resource would collide with an existing one."""
