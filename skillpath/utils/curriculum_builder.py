"""Rule-based personalised learning plan builder (no LLM required)."""

from __future__ import annotations

DEFAULT_WEEKS_PER_SKILL = 3
SEVERITY_HOURS = {"high": 6, "medium": 5, "low": 3}


def _skill_weeks(skill: str, resources_db: dict) -> int:
    entry = resources_db.get(skill, {})
    return int(entry.get("duration_weeks", DEFAULT_WEEKS_PER_SKILL))


def _skill_resource(skill: str, resources_db: dict) -> dict:
    entry = resources_db.get(skill, {})
    return {
        "name": entry.get("course", f"{skill} — structured self-study"),
        "platform": entry.get("platform", "Recommended"),
        "hours": _skill_weeks(skill, resources_db) * 4,
        "url": entry.get("url", ""),
    }


def build_personalized_plan(gap: dict, taxonomy: dict) -> dict:
    """Build a unique plan per employee based on their specific skill gaps."""
    missing = list(gap.get("missing_skills") or [])
    if not missing:
        return {}

    resources_db = taxonomy.get("learning_resources", {})
    severity = str(gap.get("gap_severity", "medium")).lower()
    weekly_hours = SEVERITY_HOURS.get(severity, 5)

    skill_blocks = [
        {"skill": skill, "weeks": _skill_weeks(skill, resources_db)}
        for skill in missing
    ]
    total_weeks = sum(block["weeks"] for block in skill_blocks)

    phases: list[dict] = []
    week_cursor = 1
    phase_num = 1

    for i in range(0, len(skill_blocks), 2):
        chunk = skill_blocks[i : i + 2]
        phase_weeks = sum(block["weeks"] for block in chunk)
        week_end = week_cursor + phase_weeks - 1
        skill_names = [block["skill"] for block in chunk]
        phases.append(
            {
                "phase": phase_num,
                "weeks": f"{week_cursor}-{week_end}",
                "focus": " & ".join(skill_names),
                "skills_covered": skill_names,
                "resources": [_skill_resource(block["skill"], resources_db) for block in chunk],
                "milestone": (
                    f"Apply {skill_names[0]} in a work scenario"
                    + (
                        f" and complete a mini-project using {skill_names[1]}"
                        if len(skill_names) > 1
                        else ""
                    )
                ),
            }
        )
        week_cursor = week_end + 1
        phase_num += 1

    priority = gap.get("priority_gaps") or missing[:2]

    return {
        "employee_id": gap.get("employee_id", ""),
        "employee_name": gap.get("employee_name", ""),
        "email": gap.get("email", ""),
        "current_role": gap.get("current_role", ""),
        "target_role": gap.get("target_role", ""),
        "missing_skills": missing,
        "priority_gaps": priority,
        "gap_severity": severity,
        "total_weeks": total_weeks,
        "weekly_hours_required": weekly_hours,
        "phases": phases,
        "success_metrics": [
            f"Close priority gap: {priority[0]}",
            f"Complete all {len(missing)} missing skills",
            f"Ready for {gap.get('target_role', 'target role')} interview assessment",
        ],
        "coaching_frequency": "weekly",
        "learning_summary": gap.get(
            "summary",
            f"{gap.get('employee_name', 'Employee')} needs {len(missing)} skills over {total_weeks} weeks.",
        ),
    }
