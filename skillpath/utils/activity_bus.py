"""
Thread-safe activity feed for the Streamlit dashboard.
Captures stdout from agents and derives live dashboard state.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AGENT_NAMES = (
    "gap-analyst",
    "curriculum-architect",
    "coach-agent",
    "progress-tracker",
    "hr-reporter",
)

AGENT_TAG = re.compile(
    r"\[(gap-analyst|curriculum-architect|coach-agent|progress-tracker|hr-reporter)\]"
)
GAP_LINE = re.compile(
    r"\*\*(?P<name>[^*]+)\*\*:\s*(?P<severity>HIGH|MEDIUM|LOW)\s+gap.*?(\d+)\s+skills",
    re.I,
)
PLAN_LINE = re.compile(
    r"\*\*(?P<name>[^*]+)\*\*:\s*\*\*(?P<weeks>\d+)-week\*\*",
    re.I,
)
COACH_ROOM = re.compile(
    r"Coaching room opened for \*\*(?P<name>[^*]+)\*\*.*?`coaching-(?P<room>[^`]+)`",
    re.I,
)
REPORT_SAVED = re.compile(r"Report saved to (output/hr_report_[^\s]+\.json)")


@dataclass
class EmployeeRow:
    name: str
    current_role: str = ""
    target_role: str = ""
    missing_skills: int = 0
    plan_weeks: int = 0
    status: str = "Pending"
    coach_room: str = ""


@dataclass
class DashboardState:
    running: bool = False
    stage: str = "idle"
    logs: deque = field(default_factory=lambda: deque(maxlen=400))
    employees: dict[str, EmployeeRow] = field(default_factory=dict)
    on_track: int = 0
    at_risk: int = 0
    avg_plan_weeks: float = 0.0
    latest_report: str | None = None
    error: str | None = None


class ActivityBus:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = DashboardState()

    def reset(self, employees: list[EmployeeRow] | None = None):
        with self._lock:
            self.state = DashboardState(running=True, stage="starting")
            if employees:
                self.state.employees = {e.name: e for e in employees}

    def set_running(self, running: bool):
        with self._lock:
            self.state.running = running
            if not running and self.state.stage not in ("complete", "error"):
                self.state.stage = "stopped"

    def set_error(self, message: str):
        with self._lock:
            self.state.error = message
            self.state.stage = "error"
            self.state.running = False

    def push_line(self, line: str):
        line = line.strip()
        if not line:
            return
        with self._lock:
            agent = None
            m = AGENT_TAG.search(line)
            if m:
                agent = m.group(1)
            kind = "info"
            if "Handed off" in line or "Handing off" in line or "→" in line:
                kind = "handoff"
            if "ESCALATION" in line or "at risk" in line.lower():
                kind = "escalate"
            if "complete" in line.lower() or "✅" in line:
                kind = "success"

            self.state.logs.append({"agent": agent, "text": line, "kind": kind})
            self._update_from_line(line)

    def _update_from_line(self, line: str):
        lower = line.lower()

        if "starting skill gap analysis" in lower:
            self.state.stage = "gap_analysis"
        elif "building personalised learning paths" in lower:
            self.state.stage = "curriculum"
        elif "starting" in lower and "coaching sessions" in lower:
            self.state.stage = "coaching"
        elif "monitoring" in lower and "employees" in lower:
            self.state.stage = "tracking"
        elif "generating final audit-ready report" in lower:
            self.state.stage = "report"
        elif "workflow complete" in lower:
            self.state.stage = "complete"
            self.state.running = False

        gm = GAP_LINE.search(line)
        if gm:
            name = gm.group("name").strip()
            row = self.state.employees.setdefault(name, EmployeeRow(name=name))
            row.missing_skills = int(gm.group(3))
            row.status = "Gap analysed"

        pm = PLAN_LINE.search(line)
        if pm:
            name = pm.group("name").strip()
            row = self.state.employees.setdefault(name, EmployeeRow(name=name))
            row.plan_weeks = int(pm.group("weeks"))
            row.status = "Plan ready"

        cr = COACH_ROOM.search(line)
        if cr:
            name = cr.group("name").strip()
            row = self.state.employees.setdefault(name, EmployeeRow(name=name))
            row.coach_room = f"coaching-{cr.group('room')}"
            row.status = "Coaching active"

        if "on track" in lower and "employees appear" in lower:
            m = re.search(r"all (\d+) employees", lower)
            if m:
                self.state.on_track = int(m.group(1))
                self.state.at_risk = 0
                for row in self.state.employees.values():
                    if row.status != "Pending":
                        row.status = "On track"

        if "need support" in lower:
            m = re.search(r"(\d+) on track, (\d+) need support", lower)
            if m:
                self.state.on_track = int(m.group(1))
                self.state.at_risk = int(m.group(2))

        rs = REPORT_SAVED.search(line)
        if rs:
            self.state.latest_report = rs.group(1)

        weeks = [r.plan_weeks for r in self.state.employees.values() if r.plan_weeks]
        if weeks:
            self.state.avg_plan_weeks = round(sum(weeks) / len(weeks), 1)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.state.running,
                "stage": self.state.stage,
                "logs": list(self.state.logs),
                "employees": {k: vars(v) for k, v in self.state.employees.items()},
                "on_track": self.state.on_track,
                "at_risk": self.state.at_risk,
                "avg_plan_weeks": self.state.avg_plan_weeks,
                "latest_report": self.state.latest_report,
                "error": self.state.error,
            }


BUS = ActivityBus()
