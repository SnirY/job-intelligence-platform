"""Aggregate router for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from jip_api.api.v1 import (
    applications,
    career,
    career_records,
    dashboard,
    discovery,
    health,
    insights,
    jobs,
    matches,
    processing_jobs,
    resume_authoring,
    resume_tailoring,
    resumes,
    saved_views,
    skill_candidates,
    users,
)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(users.router)
api_v1_router.include_router(career.router)
api_v1_router.include_router(career_records.router)
api_v1_router.include_router(resumes.router)
api_v1_router.include_router(applications.router)
api_v1_router.include_router(saved_views.router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(matches.router)
api_v1_router.include_router(resume_authoring.router)
api_v1_router.include_router(resume_authoring.versions_router)
api_v1_router.include_router(resume_tailoring.router)
api_v1_router.include_router(processing_jobs.router)
api_v1_router.include_router(dashboard.router)
api_v1_router.include_router(insights.router)
api_v1_router.include_router(skill_candidates.router)
api_v1_router.include_router(discovery.router)
