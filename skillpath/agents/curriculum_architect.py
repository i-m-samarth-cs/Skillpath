"""
Agent 2: Curriculum Architect
──────────────────────────────
• Receives gap analysis results from Gap Analyst via Band
• Builds a personalised weekly learning plan for each employee
• Posts plans back to Band and hands off to Coach Agent
"""

import asyncio
import json

from utils.band_sdk_client import BandSDKClient
from utils.curriculum_builder import build_personalized_plan


class CurriculumArchitectAgent:

    def __init__(self):
        self.name   = "curriculum-architect"
        self.client = BandSDKClient(
            agent_key  = self.name,
            agent_name = self.name,
        )
        self._handled_events: set[str] = set()

    async def run(self):
        await self.client.connect()
        self.client.on_message(self.handle_message)
        print(f"[{self.name}] Ready. Waiting for gap analysis results from Band...")
        await self.client.listen()

    async def handle_message(self, sender, text, data, raw):
        if data.get("event") != "gap_analysis_complete":
            return

        event_key = raw.get("id") or f"{raw.get('room_id')}:{data.get('event')}"
        if event_key in self._handled_events:
            return
        self._handled_events.add(event_key)

        room_id = raw.get("room_id")
        await self.client.join_room(room_id)
        gaps = data.get("gaps", [])
        await self.build_all_curricula(gaps, room_id)

    async def build_all_curricula(self, gaps: list, room_id: str):
        await self.client.send_message(
            f"📚 **Curriculum Architect** building personalised learning paths "
            f"for {len(gaps)} employees...",
            room_id
        )

        all_plans = []
        with open("data/skill_taxonomy.json") as f:
            taxonomy = json.load(f)

        for gap in gaps:
            plan = build_personalized_plan(gap, taxonomy)
            if plan:
                all_plans.append(plan)
                skills_preview = ", ".join(plan["missing_skills"][:3])
                if len(plan["missing_skills"]) > 3:
                    skills_preview += f" +{len(plan['missing_skills']) - 3} more"
                await self.client.send_message(
                    f"📖 **{gap['employee_name']}**: **{plan['total_weeks']}-week** plan "
                    f"({plan['weekly_hours_required']} hrs/week) — "
                    f"gaps: {skills_preview}",
                    room_id
                )
                await asyncio.sleep(0.5)

        await self.client.send_structured(
            {"event": "curricula_ready", "plans": all_plans},
            room_id
        )
        await self.client.send_message(
            f"✅ **Curriculum Architect** done. {len(all_plans)} unique learning plans ready.\n"
            f"@coach-agent — please begin employee coaching sessions.",
            room_id
        )
        print(f"[{self.name}] Handed off {len(all_plans)} plans to coach-agent.")


async def main():
    agent = CurriculumArchitectAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
