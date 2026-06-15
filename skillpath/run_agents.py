"""
Shared agent orchestrator — used by main.py and the Streamlit app.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Callable

from agents.coach_agent import CoachAgent
from agents.curriculum_architect import CurriculumArchitectAgent
from agents.gap_analyst import GapAnalystAgent
from agents.hr_reporter import HRReporterAgent
from agents.progress_tracker import ProgressTrackerAgent


async def run_all_agents() -> None:
    agents = [
        GapAnalystAgent(),
        CurriculumArchitectAgent(),
        CoachAgent(),
        ProgressTrackerAgent(),
        HRReporterAgent(),
    ]
    await asyncio.gather(*(agent.run() for agent in agents))


def start_agents_in_background(on_error: Callable[[Exception], None] | None = None) -> threading.Thread:
    """Start the 5 Band agents on a daemon thread (for Streamlit)."""

    def _runner() -> None:
        try:
            asyncio.run(run_all_agents())
        except Exception as exc:
            if on_error:
                on_error(exc)

    thread = threading.Thread(target=_runner, name="skillpath-agents", daemon=True)
    thread.start()
    return thread
