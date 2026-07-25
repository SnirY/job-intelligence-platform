"""Liveness and readiness endpoints.

Liveness answers "is this process running". Readiness answers "can this process
serve traffic", which requires PostgreSQL and Redis to actually respond — a
readiness probe that only returns ``ok`` would hide exactly the failure it
exists to detect.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from jip_api import __version__
from jip_api.core.errors import error_response
from jip_api.core.responses import DataResponse
from jip_api.infrastructure.db.session import get_engine
from jip_api.infrastructure.tasks.dispatcher import get_redis
from jip_config import Environment, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

DependencyStatus = Literal["ok", "unavailable"]


class HealthPayload(BaseModel):
    """Liveness payload."""

    status: Literal["ok"]
    service: str
    version: str
    environment: Environment


class DependencyReport(BaseModel):
    """Result of probing a single downstream dependency."""

    status: DependencyStatus
    detail: str | None = None


class ReadinessPayload(BaseModel):
    """Readiness payload including per-dependency results."""

    status: Literal["ready", "degraded"]
    dependencies: dict[str, DependencyReport]


def _check_database() -> DependencyReport:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database readiness probe failed", exc_info=exc)
        return DependencyReport(status="unavailable", detail=type(exc).__name__)
    return DependencyReport(status="ok")


def _check_redis() -> DependencyReport:
    try:
        get_redis().ping()
    except RedisError as exc:
        logger.warning("Redis readiness probe failed", exc_info=exc)
        return DependencyReport(status="unavailable", detail=type(exc).__name__)
    return DependencyReport(status="ok")


@router.get(
    "/health",
    response_model=DataResponse[HealthPayload],
    summary="Liveness probe",
)
def health() -> DataResponse[HealthPayload]:
    """Report that the API process is up. Does not touch dependencies."""
    settings = get_settings()
    return DataResponse(
        data=HealthPayload(
            status="ok",
            service="api",
            version=__version__,
            environment=settings.environment,
        )
    )


@router.get(
    "/health/ready",
    response_model=DataResponse[ReadinessPayload],
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "A dependency is unavailable"}},
)
def readiness() -> Response | DataResponse[ReadinessPayload]:
    """Probe PostgreSQL and Redis, returning 503 when either is unusable."""
    dependencies = {"database": _check_database(), "redis": _check_redis()}
    degraded = [name for name, report in dependencies.items() if report.status != "ok"]

    if degraded:
        return error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="SERVICE_UNAVAILABLE",
            message="One or more required dependencies are unavailable.",
            details={
                "unavailable": degraded,
                "dependencies": {
                    name: report.model_dump() for name, report in dependencies.items()
                },
            },
        )

    return DataResponse(data=ReadinessPayload(status="ready", dependencies=dependencies))
