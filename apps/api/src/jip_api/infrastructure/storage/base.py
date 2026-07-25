"""The object storage contract.

``docs/10-api-contracts.md`` requires upload, download, delete, and signed URL.
Keeping it a Protocol means the application layer never learns which backend is
in use, and tests substitute an in-memory double without touching a network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StorageError(Exception):
    """The object store could not satisfy the request."""


class ObjectNotFoundError(StorageError):
    """No object exists at that key."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Identity of a stored object."""

    key: str
    size_bytes: int
    content_type: str


class ObjectStorage(Protocol):
    """Store and retrieve user-uploaded files."""

    def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        """Store ``data`` at ``key``, replacing anything already there."""
        ...

    def download(self, key: str) -> bytes:
        """Return the object's bytes, raising :class:`ObjectNotFoundError` if absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object. Deleting a missing key is not an error."""
        ...

    def create_signed_url(self, key: str, *, expires_in_seconds: int = 900) -> str:
        """Return a time-limited URL for direct download.

        Signed rather than public: resume files are personal data, and a
        guessable permanent URL would make them readable by anyone who learned
        the key (``docs/04-system-architecture.md``, security requirements).
        """
        ...
