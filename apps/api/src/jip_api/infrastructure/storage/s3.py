"""S3-compatible object storage.

Works against AWS S3, MinIO, Cloudflare R2, or any other S3 API implementation,
which is why the endpoint URL is configuration rather than a constant.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from jip_api.infrastructure.storage.base import (
    ObjectNotFoundError,
    ObjectStorage,
    StorageError,
    StoredObject,
)
from jip_config import Settings, get_settings

logger = logging.getLogger(__name__)


class S3ObjectStorage:
    """:class:`ObjectStorage` backed by the S3 API."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Resumes are personal data. Server-side encryption costs
                # nothing here and means a leaked backup is not a leaked resume.
                ServerSideEncryption="AES256",
            )
        except Exception as exc:  # boto3 raises a wide family of client errors
            logger.warning("Object upload failed", exc_info=exc, extra={"key": key})
            raise StorageError(f"could not store object: {exc}") from exc

        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def download(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing_key(exc):
                raise ObjectNotFoundError(f"no object at {key!r}") from exc
            logger.warning("Object download failed", exc_info=exc, extra={"key": key})
            raise StorageError(f"could not read object: {exc}") from exc

        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing_key(exc):
                return
            raise StorageError(f"could not delete object: {exc}") from exc

    def create_signed_url(self, key: str, *, expires_in_seconds: int = 900) -> str:
        try:
            url: str = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
        except Exception as exc:
            raise StorageError(f"could not sign url: {exc}") from exc
        return url


def _is_missing_key(exc: Exception) -> bool:
    """Whether a boto3 error means "no such key".

    Matched on the response code rather than the exception class: botocore
    generates those classes dynamically, so importing them couples this module
    to botocore internals.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = response.get("Error", {}).get("Code")
    return code in {"NoSuchKey", "404", "NotFound"}


def build_s3_client(settings: Settings) -> Any:
    """Construct a boto3 S3 client from settings."""
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url or None,
        region_name=settings.storage_region,
        aws_access_key_id=settings.storage_access_key or None,
        aws_secret_access_key=settings.storage_secret_key or None,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.connect_timeout_seconds * 2,
            # MinIO and other self-hosted implementations rarely have
            # virtual-host DNS set up, so address buckets by path.
            s3={"addressing_style": "path"},
        ),
    )


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Return the process-wide object storage adapter."""
    settings = get_settings()
    if not settings.storage_bucket:
        raise ValueError("Object storage is not configured: set JIP_STORAGE_BUCKET.")
    return S3ObjectStorage(build_s3_client(settings), settings.storage_bucket)


def reset_storage_cache() -> None:
    """Drop the cached adapter. Used by tests that reconfigure storage."""
    get_object_storage.cache_clear()
