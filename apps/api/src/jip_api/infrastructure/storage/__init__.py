"""Object storage adapters.

Uploaded files never go in the relational database
(``docs/04-system-architecture.md``); they live in S3-compatible storage behind
the :class:`ObjectStorage` interface.
"""

from jip_api.infrastructure.storage.base import ObjectStorage, StorageError, StoredObject
from jip_api.infrastructure.storage.s3 import (
    S3ObjectStorage,
    get_object_storage,
    reset_storage_cache,
)

__all__ = [
    "ObjectStorage",
    "S3ObjectStorage",
    "StorageError",
    "StoredObject",
    "get_object_storage",
    "reset_storage_cache",
]
