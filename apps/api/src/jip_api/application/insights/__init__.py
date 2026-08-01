"""Career insights: what the user's own saved jobs keep asking for."""

from jip_api.application.insights.demand import DemandReport, SkillDemand, build_demand, build_gaps
from jip_api.application.insights.gaps import GapState, gap_state

__all__ = ["DemandReport", "GapState", "SkillDemand", "build_demand", "build_gaps", "gap_state"]
