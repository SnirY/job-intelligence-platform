"""Test doubles for the resume import integration tests.

An in-memory object store and a recording dispatcher. Both implement the real
Protocols, so the code under test is the production code — only the network is
absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jip_api.infrastructure.storage.base import ObjectNotFoundError, StoredObject
from jip_api.infrastructure.tasks.dispatcher import DispatchedTask


class InMemoryStorage:
    """:class:`~jip_api.infrastructure.storage.base.ObjectStorage` in a dict.

    Real S3 semantics are covered in CI against MinIO. What these tests need is
    the guarantee that the file left the database, which a dict demonstrates as
    well as a bucket does.
    """

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.signed: list[tuple[str, int]] = []

    def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        self.objects[key] = (data, content_type)
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def download(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise ObjectNotFoundError(f"no object at {key!r}") from exc

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def create_signed_url(self, key: str, *, expires_in_seconds: int = 900) -> str:
        self.signed.append((key, expires_in_seconds))
        return f"https://storage.test/{key}?X-Amz-Signature=abc&X-Amz-Expires={expires_in_seconds}"


@dataclass
class RecordingDispatcher:
    """Records enqueued tasks instead of running them.

    The pipeline is driven directly in these tests, so the queue's only role is
    to prove the API asked for the work — and, when ``fail`` is set, that a
    queue outage is handled without losing the upload.
    """

    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    fail: bool = False

    def enqueue(
        self, task_path: str, *args: Any, queue: str | None = None, **kwargs: Any
    ) -> DispatchedTask:
        if self.fail:
            raise ConnectionError("redis is down")
        self.calls.append((task_path, args))
        return DispatchedTask(id=f"task-{len(self.calls)}", queue=queue or "default")
