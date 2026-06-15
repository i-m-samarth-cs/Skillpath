"""
Agent 1: Gap Analyst
────────────────────
• Reads employees.csv
• Compares current skills against target role requirements (skill_taxonomy.json)
• Posts structured skill-gap findings to Band main room
• Tags @curriculum-architect to hand off
"""

import asyncio
import json
import pandas as pd

from utils.band_sdk_client import BandSDKClient
from utils.llm_client  import AIMLClient

SYSTEM_PROMPT = """
You are a skilled HR analyst specialising in workforce planning.
Given an employee's profile and target role requirements, you identify
skill gaps clearly and concisely.

Return ONLY valid JSON in this exact format:
{
  "employee_id": "...",
  "employee_name": "...",
  "current_role": "...",
  "target_role": "...",
  "missing_skills": ["skill1", "skill2"],
  "priority_gaps": ["most critical skill", "second most critical"],
  "gap_severity": "high|medium|low",
  "summary": "2-sentence human-readable summary"
}
"""


class GapAnalystAgent:

    def __init__(self):
        self.name   = "gap-analyst"
        self.client = BandSDKClient(
            agent_key  = self.name,
            agent_name = self.name,
        )
        self.llm      = AIMLClient()
        self.triggered = False
        self._running  = False

    # ── Main entry ────────────────────────────────────────────────────────────

    async def run(self):
        await self.client.connect()
        self.client.on_message(self.handle_message)

        # Auto-trigger the workflow if no external request arrives
        asyncio.create_task(self._auto_start())

        print(f"[{self.name}] Waiting for trigger in Band... or auto-starting if idle")
        await self.client.listen()

    async def _auto_start(self):
        try:
            await asyncio.sleep(10)
            if self.triggered:
                return

            room_id = self.client.room_id
            if not room_id:
                room_id = await self.client.create_room("skillpath-main-room")

            self.triggered = True
            await self.client.send_message(
                "🤖 Auto-starting SkillPath gap analysis workflow.",
                room_id
            )
            await self.analyse_all_employees(room_id)
        except Exception as exc:
            self.triggered = False
            print(f"[{self.name}] Auto-start failed: {exc}")

    # ── Message handler ───────────────────────────────────────────────────────

    async def handle_message(self, sender, text, data, raw):
        sender_id = raw.get("sender_id")
        if sender_id == self.client.agent_id or self.client.is_peer_agent(sender_id):
            return
        if data.get("event"):
            return

        text_lower = text.lower()
        explicit_trigger = (
            f"@{self.name}" in text_lower
            or "start gap analysis" in text_lower
            or "run gap analysis" in text_lower
        )
        if not explicit_trigger:
            return
        if self._running:
            return

        self.triggered = True
        self._running = True
        try:
            room_id = raw.get("room_id")
            await self.analyse_all_employees(room_id)
        finally:
            self._running = False

    # ── Core logic ────────────────────────────────────────────────────────────

    async def analyse_all_employees(self, room_id: str):
        await self.client.join_room(room_id)
        await self.client.ensure_skillpath_peers(room_id)
        await self.client.send_message(
            "📋 **Gap Analyst** starting skill gap analysis for all employees...",
            room_id
        )

        # Load data
        employees = pd.read_csv("data/employees.csv")
        with open("data/skill_taxonomy.json") as f:
            taxonomy = json.load(f)

        all_gaps = []

        for _, emp in employees.iterrows():
            gap = await self.analyse_employee(emp, taxonomy)
            if gap:
                all_gaps.append(gap)
                await self.client.send_message(
                    f"🔍 **{emp['name']}**: {gap['gap_severity'].upper()} gap — "
                    f"missing {len(gap['missing_skills'])} skills for {emp['target_role']}",
                    room_id
                )
                await asyncio.sleep(0.5)

        # Post full structured findings and hand off to Curriculum Architect
        await self.client.send_structured(
            {"event": "gap_analysis_complete", "gaps": all_gaps},
            room_id
        )
        await self.client.send_message(
            f"✅ **Gap Analyst** done. Found gaps for {len(all_gaps)} employees.\n"
            f"@curriculum-architect — please build learning paths from these gaps.",
            room_id
        )
        print(f"[{self.name}] Analysis complete. Handed off to curriculum-architect.")

    async def analyse_employee(self, emp: dict, taxonomy: dict) -> dict | None:
        target_role = emp.get("target_role", "")
        role_data   = taxonomy["roles"].get(target_role)
        if not role_data:
            return None

        current_skills  = [s.strip() for s in str(emp.get("current_skills", "")).split(",")]
        required_skills = role_data["required_skills"]
        missing         = [s for s in required_skills if s not in current_skills]

        if not missing:
            return None

        user_prompt = f"""
Employee: {emp['name']}
Current Role: {emp['current_role']}
Target Role: {emp['target_role']}
Current Skills: {current_skills}
Required Skills for Target Role: {required_skills}
Missing Skills: {missing}
Years of Experience: {emp['years_experience']}

Perform a skill gap analysis and return the JSON.
"""
        try:
            raw_json = self.llm.chat(SYSTEM_PROMPT, user_prompt)
            raw_json = raw_json.strip().lstrip("```json").lstrip("```").rstrip("```")
            gap = json.loads(raw_json)
            gap["email"] = emp.get("email", "")
            return gap
        except Exception as e:
            print(f"[{self.name}] LLM parse error for {emp['name']}: {e}")
            # Fallback: return basic gap data without LLM
            return {
                "employee_id":   emp["employee_id"],
                "employee_name": emp["name"],
                "email":         emp.get("email", ""),
                "current_role":  emp["current_role"],
                "target_role":   emp["target_role"],
                "missing_skills": missing,
                "priority_gaps": missing[:2],
                "gap_severity":  "high" if len(missing) > 4 else "medium",
                "summary":       f"{emp['name']} needs {len(missing)} skills to become a {target_role}.",
            }


async def main():
    agent = GapAnalystAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
