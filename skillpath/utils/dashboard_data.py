"""Load employee seed data for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from utils.activity_bus import EmployeeRow


def load_employee_rows() -> list[EmployeeRow]:
    csv_path = Path("data/employees.csv")
    tax_path = Path("data/skill_taxonomy.json")
    if not csv_path.exists():
        return []

    taxonomy: dict = {}
    if tax_path.exists():
        with open(tax_path, encoding="utf-8") as f:
            taxonomy = json.load(f)

    rows: list[EmployeeRow] = []
    for _, emp in pd.read_csv(csv_path).iterrows():
        current = [s.strip() for s in str(emp.get("current_skills", "")).split(",") if s.strip()]
        role_data = taxonomy.get("roles", {}).get(emp.get("target_role", ""), {})
        required = role_data.get("required_skills", [])
        missing = len([s for s in required if s not in current])
        rows.append(
            EmployeeRow(
                name=str(emp["name"]),
                current_role=str(emp.get("current_role", "")),
                target_role=str(emp.get("target_role", "")),
                missing_skills=missing,
                status="Enrolled",
            )
        )
    return rows


def load_latest_hr_report() -> dict | None:
    out = Path("output")
    if not out.exists():
        return None
    reports = sorted(out.glob("hr_report_*.json"), reverse=True)
    if not reports:
        return None
    with open(reports[0], encoding="utf-8") as f:
        return json.load(f)
