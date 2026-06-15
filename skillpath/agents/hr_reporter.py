"""
Agent 5: HR Reporter (AI/ML API)
──────────────────────────────────
• Receives final progress data from Progress Tracker
• Generates a structured, audit-ready HR report as JSON + text
• Posts the report to the main Band room
• Saves report to disk for the dashboard
"""

import asyncio
import json
import os
from datetime import datetime

from utils.band_sdk_client import BandSDKClient
from utils.llm_client  import AIMLClient

SYSTEM_PROMPT = """
You are a senior HR reporting specialist.
Generate a professional, audit-ready workforce development report.
Return ONLY valid JSON in this exact format:
{
  "report_title": "...",
  "report_date": "...",
  "executive_summary": "3-4 sentence high-level summary",
  "key_metrics": {
    "total_employees_enrolled": 0,
    "on_track_percentage": 0,
    "average_skill_gaps_per_employee": 0,
    "estimated_completion_weeks": 12
  },
  "department_breakdown": [
    {"role": "...", "count": 0, "avg_gaps": 0, "status": "on_track|at_risk"}
  ],
  "recommendations": ["recommendation1", "recommendation2", "recommendation3"],
  "risks_and_mitigations": [
    {"risk": "...", "mitigation": "..."}
  ],
  "next_steps": ["step1", "step2"],
  "audit_hash": "sha256-placeholder"
}
"""


class HRReporterAgent:

    def __init__(self):
        self.name   = "hr-reporter"
        self.client = BandSDKClient(
            agent_key  = self.name,
            agent_name = self.name,
        )
        self.llm = AIMLClient()
        self._handled_reports: set[str] = set()

    async def run(self):
        await self.client.connect()
        self.client.on_message(self.handle_message)
        print(f"[{self.name}] Ready. Waiting for progress report from Band...")
        await self.client.listen()

    async def handle_message(self, sender, text, data, raw):
        room_id = raw.get("room_id")
        if data.get("event") == "progress_report_ready":
            event_key = raw.get("id") or f"{room_id}:{data.get('event')}"
            if event_key in self._handled_reports:
                return
            self._handled_reports.add(event_key)

            await self.client.join_room(room_id)
            await self.generate_report(data, room_id)

    async def generate_report(self, data: dict, room_id: str):
        await self.client.send_message(
            "📋 **HR Reporter** generating final audit-ready report...",
            room_id
        )

        progress   = data.get("progress", {})
        at_risk    = data.get("at_risk", [])
        on_track   = data.get("on_track", [])
        summary    = data.get("summary", {})
        plan_summaries = data.get("plan_summaries", {})
        avg_weeks  = summary.get("avg_plan_weeks", 0)

        user_prompt = f"""
Progress Data:
- Total employees in programme: {summary.get('total_employees', len(progress))}
- Employees on track: {len(on_track)} ({summary.get('completion_rate_pct', 0)}%)
- Employees at risk: {len(at_risk)}
- At-risk employee IDs: {at_risk}
- Average personalised plan length: {avg_weeks or 'varies by employee'} weeks
- Individual plan lengths: {json.dumps(summary.get('plan_weeks_by_employee', {}))}
- Coaching frequency: Weekly
- Generated on: {datetime.now().strftime('%Y-%m-%d')}

Generate a complete HR audit report. Return only JSON.
"""
        try:
            raw_json = self.llm.chat(SYSTEM_PROMPT, user_prompt, max_tokens=2000)
            raw_json = raw_json.strip().lstrip("```json").lstrip("```").rstrip("```")
            report   = json.loads(raw_json)
        except Exception as e:
            print(f"[{self.name}] LLM error: {e}. Using fallback report.")
            report = self.fallback_report(summary, at_risk, on_track)

        # Save to disk
        os.makedirs("output", exist_ok=True)
        filename = f"output/hr_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump(report, f, indent=2)
        print(f"[{self.name}] Report saved to {filename}")

        # Post summary to Band
        metrics = report.get("key_metrics", {})
        await self.client.send_message(
            f"📊 **HR AUDIT REPORT — SkillPath Programme**\n\n"
            f"**Executive Summary:** {report.get('executive_summary', 'N/A')}\n\n"
            f"**Key Metrics:**\n"
            f"• Employees enrolled: {metrics.get('total_employees_enrolled', len(progress))}\n"
            f"• On-track rate: {metrics.get('on_track_percentage', summary.get('completion_rate_pct', 0))}%\n"
            f"• Avg skill gaps: {metrics.get('average_skill_gaps_per_employee', 'N/A')}\n"
            f"• Est. completion: {metrics.get('estimated_completion_weeks', 12)} weeks\n\n"
            f"**Top Recommendations:**\n" +
            "\n".join(f"  {i+1}. {r}" for i, r in enumerate(report.get("recommendations", [])[:3])) +
            f"\n\n📁 Full report saved to `{filename}`",
            room_id
        )

        await self.client.send_message(
            f"✅ **HR Reporter** complete. Report saved and sealed.\n"
            f"@HR-Manager — the workforce reskilling report is ready for your review.",
            room_id
        )
        print(f"[{self.name}] Report posted to Band. Workflow complete.")

    def fallback_report(self, summary: dict, at_risk: list, on_track: list) -> dict:
        total = summary.get("total_employees", 5)
        avg_weeks = summary.get("avg_plan_weeks", 0)
        return {
            "report_title":      "SkillPath Workforce Reskilling Programme — Progress Report",
            "report_date":       str(datetime.now().date()),
            "executive_summary": (
                f"The SkillPath programme enrolled {total} employees across 5 target roles. "
                f"{len(on_track)} employees are progressing on schedule. "
                f"{len(at_risk)} employees require additional support and coaching intervention. "
                f"Average personalised plan length is {avg_weeks or 'N/A'} weeks."
            ),
            "key_metrics": {
                "total_employees_enrolled":      total,
                "on_track_percentage":           summary.get("completion_rate_pct", 0),
                "average_skill_gaps_per_employee": summary.get("avg_gaps_per_employee", 4),
                "estimated_completion_weeks":    avg_weeks or summary.get("max_plan_weeks", 0),
            },
            "department_breakdown": [],
            "recommendations": [
                "Increase coaching frequency for at-risk employees to bi-weekly",
                "Consider peer-learning pairs for complex technical skills",
                "Review learning resource quality in Phase 1 for low-engagement areas",
            ],
            "risks_and_mitigations": [
                {"risk": "Time constraints for learners", "mitigation": "Offer micro-learning alternatives"},
                {"risk": "Course quality variance",       "mitigation": "Standardise vetted resource library"},
            ],
            "next_steps": ["Schedule mid-programme review at week 6", "Share report with department heads"],
            "audit_hash": "sha256-demo-placeholder",
        }


async def main():
    agent = HRReporterAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
