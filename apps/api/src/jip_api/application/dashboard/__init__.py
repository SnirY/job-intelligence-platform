"""The dashboard: everything that already exists, said once, in one place."""

from jip_api.application.dashboard.actions import ActionKind, NextAction
from jip_api.application.dashboard.service import DashboardView, build_dashboard

__all__ = ["ActionKind", "DashboardView", "NextAction", "build_dashboard"]
