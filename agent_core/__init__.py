"""
agent_core — CrewAI agents and scenario task builders for TRIDENT.
"""
from agent_core.agents import (
    build_hr_specialist,
    build_system_admin,
    build_research_agent,
    build_summary_agent,
)
from agent_core.tasks import build_s0_task, build_s1_task, build_s2_tasks, build_s3_task

__all__ = [
    # Agents
    "build_hr_specialist",
    "build_system_admin",
    "build_research_agent",
    "build_summary_agent",
    # Tasks
    "build_s0_task",
    "build_s1_task",
    "build_s2_tasks",
    "build_s3_task",
]
