"""
Agent 4: Progress Tracker (Featherless AI)
───────────────────────────────────────────
• Monitors coaching sessions and collects progress signals
• Flags at-risk employees who haven't responded or seem behind
• Escalates to HR manager (human) via Band when intervention needed
• Hands final progress report to HR Reporter
"""

import asyncio
import json
from datetime import datetime

from utils.band_sdk_client import BandSDKClient
from utils.llm_client  import FeatherlessClient

SYSTEM_PROMPT = """
You are an HR analytics specialist monitoring employee learning progress.
Analyse progress signals and identify employees who need intervention.
Return ONLY valid JSON.
"""


class ProgressTrackerAgent:

    def __init__(self):
        self.name   = "progress-tracker"
        self.client = BandSDKClient(
            agent_key  = self.name,
            agent_name = self.name,
        )
        self.llm      = FeatherlessClient()
        self.progress = {}   # employee_id → {on_track, updates, last_seen}
        self.rooms    = {}
        self.plan_summaries: dict[str, dict] = {}
        self._monitoring_rooms: set[str] = set()
        self._report_sent: set[str] = set()

    async def run(self):
        await self.client.connect()
        self.client.on_message(self.handle_message)
        print(f"[{self.name}] Ready. Monitoring coaching sessions...")
        await self.client.listen()

    async def handle_message(self, sender, text, data, raw):
        room_id = raw.get("room_id")

        # Coaching started → start monitoring
        if data.get("event") == "coaching_started":
            if room_id in self._monitoring_rooms:
                return
            self._monitoring_rooms.add(room_id)

            await self.client.join_room(room_id)
            emp_ids = data.get("employee_ids", [])
            self.rooms = data.get("rooms", {})
            self.plan_summaries = data.get("plan_summaries", {})
            for emp_id in emp_ids:
                self.progress[emp_id] = {
                    "on_track": True,
                    "updates":  [],
                    "last_seen": str(datetime.now()),
                }
            await self.client.send_message(
                f"📊 **Progress Tracker** monitoring {len(emp_ids)} employees.",
                room_id
            )
            # Schedule a progress check after a delay (simulates end of week 1)
            asyncio.create_task(self.run_weekly_check(room_id))

        # Receive progress updates from Coach Agent
        elif data.get("event") == "progress_update":
            emp_id   = data.get("employee_id")
            on_track = data.get("on_track", True)
            if emp_id in self.progress:
                self.progress[emp_id]["on_track"]  = on_track
                self.progress[emp_id]["last_seen"] = str(datetime.now())
                self.progress[emp_id]["updates"].append(data.get("last_reply", ""))
                print(f"[{self.name}] Progress update for {emp_id}: on_track={on_track}")

    async def run_weekly_check(self, room_id: str):
        """Simulates an end-of-week progress review."""
        await asyncio.sleep(30)   # In production, this would be 7 days
        await self.weekly_report(room_id)

    async def weekly_report(self, room_id: str):
        if room_id in self._report_sent:
            return
        self._report_sent.add(room_id)

        await self.client.send_message(
            "📊 **Progress Tracker** — running weekly progress review...",
            room_id
        )

        at_risk  = []
        on_track = []

        for emp_id, data in self.progress.items():
            if data["on_track"]:
                on_track.append(emp_id)
            else:
                at_risk.append(emp_id)

        # Flag at-risk employees for HR manager (human escalation)
        if at_risk:
            await self.client.send_message(
                f"⚠️ **ESCALATION — Human Review Required**\n"
                f"{len(at_risk)} employee(s) appear at risk: {', '.join(at_risk)}\n"
                f"@HR-Manager please review and approve intervention.",
                room_id
            )
        else:
            await self.client.send_message(
                f"✅ All {len(on_track)} employees appear on track this week.",
                room_id
            )

        # Generate analytics using LLM
        summary = self.build_analytics_summary()

        # Hand off to HR Reporter
        await self.client.send_structured(
            {
                "event":    "progress_report_ready",
                "progress": self.progress,
                "at_risk":  at_risk,
                "on_track": on_track,
                "summary":  summary,
                "plan_summaries": self.plan_summaries,
            },
            room_id
        )
        await self.client.send_message(
            f"📈 Weekly tracking complete. {len(on_track)} on track, {len(at_risk)} need support.\n"
            f"@hr-reporter — please generate the final HR audit report.",
            room_id
        )

    def build_analytics_summary(self) -> dict:
        total    = len(self.progress)
        on_track = sum(1 for d in self.progress.values() if d["on_track"])
        plan_weeks = {
            emp_id: info.get("total_weeks", 0)
            for emp_id, info in self.plan_summaries.items()
        }
        weeks_values = [w for w in plan_weeks.values() if w]
        avg_gaps = 0.0
        if self.plan_summaries:
            gap_counts = [len(info.get("missing_skills", [])) for info in self.plan_summaries.values()]
            avg_gaps = round(sum(gap_counts) / len(gap_counts), 1)

        return {
            "total_employees":    total,
            "on_track_count":     on_track,
            "at_risk_count":      total - on_track,
            "completion_rate_pct": round((on_track / total * 100) if total else 0, 1),
            "generated_at":       str(datetime.now()),
            "plan_weeks_by_employee": plan_weeks,
            "avg_plan_weeks":     round(sum(weeks_values) / len(weeks_values), 1) if weeks_values else 0,
            "max_plan_weeks":     max(weeks_values) if weeks_values else 0,
            "avg_gaps_per_employee": avg_gaps,
        }


async def main():
    agent = ProgressTrackerAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
