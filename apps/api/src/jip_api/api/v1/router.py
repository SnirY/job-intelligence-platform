"""Aggregate router for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from jip_api.api.v1 import (
    career,
    career_records,
    health,
    jobs,
    matches,
    processing_jobs,
    resumes,
    users,
)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(users.router)
api_v1_router.include_router(career.router)
api_v1_router.include_router(career_records.router)
api_v1_router.include_router(resumes.router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(matches.router)
api_v1_router.include_router(processing_jobs.router)
