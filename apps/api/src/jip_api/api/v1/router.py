"""Aggregate router for ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from jip_api.api.v1 import health, users

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(users.router)
