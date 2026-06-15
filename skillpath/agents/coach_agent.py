"""
Agent 3: Coach Agent (Anthropic Claude)
────────────────────────────────────────
• Receives learning plans from Curriculum Architect
• Opens a per-employee Band sub-room for 1:1 coaching
• Sends personalised gap + learning guidance; responds to employee messages
• Posts progress signals to main room for Progress Tracker
"""

import asyncio
import json

from utils.band_sdk_client import BandSDKClient
from utils.llm_client  import AnthropicClient

COACH_SYSTEM = """
You are a warm, encouraging professional learning coach for SkillPath employees.
You know the employee's skill gaps, target role, and personalised learning plan.
Keep replies SHORT (3-5 sentences), specific to their gaps and current phase.
Reference their missing skills and recommended resources by name when relevant.
Ask exactly ONE follow-up question to keep the conversation going.
If they share progress or blockers, give one concrete next step.
"""


class CoachAgent:

    def __init__(self):
        self.name   = "coach-agent"
        self.client = BandSDKClient(
            agent_key  = self.name,
            agent_name = self.name,
        )
        self.llm       = AnthropicClient()
        self.plans     = {}   # employee_id → plan
        self.rooms     = {}   # employee_id → room_id
        self.room_to_employee: dict[str, str] = {}
        self.conversations: dict[str, list[dict]] = {}
        self.main_room = None
        self._sessions_started: set[str] = set()

    async def run(self):
        await self.client.connect()
        self.client.on_message(self.handle_message)
        print(f"[{self.name}] Ready. Waiting for curricula from Band...")
        await self.client.listen()

    async def handle_message(self, sender, text, data, raw):
        room_id = raw.get("room_id")
        sender_id = raw.get("sender_id")

        if data.get("event") == "curricula_ready":
            event_key = raw.get("id") or f"{room_id}:{len(data.get('plans', []))}"
            if event_key in self._sessions_started:
                return
            self._sessions_started.add(event_key)

            self.main_room = room_id
            plans = data.get("plans", [])
            await self.client.join_room(room_id)
            await self.start_coaching_sessions(plans, room_id)
            return

        if room_id in self.room_to_employee and not self.client.is_peer_agent(sender_id):
            await self.handle_employee_reply(sender, text, room_id)

    async def start_coaching_sessions(self, plans: list, main_room_id: str):
        await self.client.send_message(
            f"🧑‍🏫 **Coach Agent** starting {len(plans)} personalised coaching sessions...\n"
            f"Employees: open your private coaching room in Band and reply to get tailored guidance.",
            main_room_id
        )
        for plan in plans:
            self.plans[plan["employee_id"]] = plan
            await self.open_employee_room(plan, main_room_id)
            await asyncio.sleep(1)

        await self.client.send_structured(
            {
                "event": "coaching_started",
                "employee_ids": list(self.plans.keys()),
                "rooms": self.rooms,
                "plan_summaries": {
                    emp_id: {
                        "employee_name": p.get("employee_name"),
                        "total_weeks": p.get("total_weeks"),
                        "weekly_hours": p.get("weekly_hours_required"),
                        "missing_skills": p.get("missing_skills", []),
                        "target_role": p.get("target_role"),
                    }
                    for emp_id, p in self.plans.items()
                },
            },
            main_room_id
        )
        await self.client.send_message(
            f"✅ **Coach Agent** opened coaching rooms for {len(plans)} employees.\n"
            f"@progress-tracker — please begin monitoring employee progress.",
            main_room_id
        )

    async def open_employee_room(self, plan: dict, main_room_id: str):
        emp_name = plan.get("employee_name", "Employee")
        emp_id   = plan.get("employee_id", "unknown")
        email    = plan.get("email", "")

        room_id = await self.client.create_room(f"coaching-{emp_id}", add_peers=False)
        self.rooms[emp_id] = room_id
        self.room_to_employee[room_id] = emp_id
        self.conversations[emp_id] = []

        checkin = self.build_coaching_brief(plan)
        await self.client.send_message(checkin, room_id)

        invite = (
            f"📬 **{emp_name}** — your private coaching room is ready (`coaching-{emp_id}`).\n"
            f"• **Plan length:** {plan['total_weeks']} weeks | **Focus:** {plan['target_role']}\n"
            f"• **Join this room in Band** and message the coach with questions about your skill gaps.\n"
        )
        if email:
            invite += f"• Registered email: `{email}`\n"
        invite += f"• Room ID: `{room_id}`"
        await self.client.send_message(invite, main_room_id)

    def build_coaching_brief(self, plan: dict) -> str:
        """Detailed first message: skill gaps, what to learn, and timeline."""
        emp_name = plan.get("employee_name", "there")
        missing  = plan.get("missing_skills", [])
        priority = plan.get("priority_gaps", [])
        phases   = plan.get("phases", [{}])
        phase1   = phases[0] if phases else {}

        lines = [
            f"Hi **{emp_name}**! 👋 I'm your SkillPath coach.",
            "",
            f"**Career path:** {plan.get('current_role', '?')} → **{plan.get('target_role', '?')}**",
            f"**Your timeline:** {plan['total_weeks']} weeks at {plan['weekly_hours_required']} hrs/week "
            f"({plan.get('gap_severity', 'medium').upper()} gap)",
            "",
            f"**Skill gaps to close ({len(missing)} skills):**",
        ]
        lines.extend(f"  • {skill}" for skill in missing)
        lines.extend([
            "",
            "**Start with these priorities:**",
        ])
        lines.extend(f"  🎯 {skill}" for skill in priority)

        if phase1:
            lines.extend([
                "",
                f"**Phase 1 (weeks {phase1.get('weeks', '?')}):** {phase1.get('focus', 'Foundation')}",
                f"**Milestone:** {phase1.get('milestone', 'Complete phase 1 skills')}",
                "",
                "**Recommended resources:**",
            ])
            for res in phase1.get("resources", []):
                url_bit = f" — {res['url']}" if res.get("url") else ""
                lines.append(f"  📚 {res.get('name', 'Course')} ({res.get('platform', 'Online')}){url_bit}")

        lines.extend([
            "",
            "**How to use this room:** Reply anytime with:",
            "  • What you've studied this week",
            "  • Which skill feels hardest",
            "  • Questions about what to learn next",
            "",
            "What would you like to focus on first — your top priority skill or your current work schedule?",
        ])
        return "\n".join(lines)

    async def handle_employee_reply(self, sender: str, text: str, room_id: str):
        emp_id = self.room_to_employee.get(room_id)
        if not emp_id:
            return

        plan = self.plans.get(emp_id, {})
        history = self.conversations.setdefault(emp_id, [])
        history.append({"role": "user", "content": text})
        history[:] = history[-6:]

        history_text = "\n".join(
            f"{'Employee' if m['role'] == 'user' else 'Coach'}: {m['content']}"
            for m in history[:-1]
        )

        phase1 = plan.get("phases", [{}])[0]
        prompt = f"""
Employee: {plan.get('employee_name', sender)}
Target role: {plan.get('target_role')}
Total plan: {plan.get('total_weeks')} weeks
Missing skills: {', '.join(plan.get('missing_skills', []))}
Priority gaps: {', '.join(plan.get('priority_gaps', []))}
Current phase focus: {phase1.get('focus', 'core skills')}
Phase milestone: {phase1.get('milestone', '')}
Resources: {json.dumps(phase1.get('resources', []), indent=2)}

Recent conversation:
{history_text or '(first reply)'}

Employee's latest message: "{text}"

Write a supportive coaching reply tailored to THEIR specific gaps and plan.
"""
        try:
            reply = self.llm.chat(COACH_SYSTEM, prompt, max_tokens=280)
        except Exception as exc:
            print(f"[{self.name}] LLM error for {emp_id}: {exc}")
            top_skill = plan.get("priority_gaps", ["your priority skill"])[0]
            reply = (
                f"Thanks for sharing, {plan.get('employee_name', 'there')}! "
                f"Based on your {plan.get('total_weeks')}-week plan, keep pushing on **{top_skill}** this week. "
                f"Tell me what's blocking you and I'll suggest a concrete next step."
            )

        history.append({"role": "assistant", "content": reply})
        await self.client.send_message(reply, room_id)

        if self.main_room:
            on_track = any(w in text.lower() for w in ["done", "finished", "completed", "good", "great", "learned"])
            await self.client.send_structured(
                {
                    "event":       "progress_update",
                    "employee_id": emp_id,
                    "on_track":    on_track,
                    "last_reply":  text[:100],
                },
                self.main_room
            )


async def main():
    agent = CoachAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
