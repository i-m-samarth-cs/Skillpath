"""
SkillPath Streamlit Dashboard
Run:  streamlit run app.py

Same 5 Band agents as `python main.py`, with a live HR dashboard UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Ensure Band config, data/, and output/ resolve correctly regardless of launch cwd.
os.chdir(Path(__file__).resolve().parent)

import pandas as pd
import streamlit as st

from run_agents import start_agents_in_background
from utils.activity_bus import BUS
from utils.dashboard_data import load_employee_rows, load_latest_hr_report
from utils.log_capture import install_log_capture

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SkillPath — HR Dashboard",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme (matches frontend/dashboard.html) ───────────────────────────────────
st.markdown(
    """
<style>
    .block-container { padding-top: 1.5rem; max-width: 1200px; }
    .skillpath-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        color: #fff; padding: 1.25rem 1.5rem; border-radius: 12px;
        margin-bottom: 1.5rem;
    }
    .skillpath-header h1 { margin: 0; font-size: 1.5rem; font-weight: 600; }
    .skillpath-header p { margin: 0.35rem 0 0; opacity: 0.85; font-size: 0.9rem; }
    .metric-card {
        background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
        padding: 1.1rem 1.25rem; height: 100%;
    }
    .metric-num { font-size: 2rem; font-weight: 700; color: #1a1a2e; line-height: 1.1; }
    .metric-lbl { font-size: 0.8rem; color: #6b7280; margin-top: 0.25rem; }
    .pipeline-step {
        text-align: center; padding: 0.6rem; border-radius: 8px;
        font-size: 0.78rem; font-weight: 600; border: 1px solid #e5e7eb;
        background: #f9fafb; color: #6b7280;
    }
    .pipeline-step.active { background: #eef2ff; border-color: #4f46e5; color: #4f46e5; }
    .pipeline-step.done { background: #dcfce7; border-color: #22c55e; color: #166534; }
    .log-box {
        background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
        padding: 1rem; font-family: ui-monospace, monospace; font-size: 0.78rem;
        max-height: 340px; overflow-y: auto; line-height: 1.65;
    }
    .log-handoff { color: #059669; }
    .log-escalate { color: #dc2626; }
    .log-success { color: #059669; }
    .agent-tag { color: #4f46e5; font-weight: 700; }
    div[data-testid="stSidebar"] { background: #f8fafc; }
</style>
""",
    unsafe_allow_html=True,
)

STAGES = [
    ("idle", "Ready"),
    ("starting", "Starting"),
    ("gap_analysis", "Gap Analysis"),
    ("curriculum", "Curriculum"),
    ("coaching", "Coaching"),
    ("tracking", "Progress"),
    ("report", "HR Report"),
    ("complete", "Complete"),
]


def _init_session() -> None:
    if "agents_thread" not in st.session_state:
        st.session_state.agents_thread = None


def _start_workflow() -> None:
    if BUS.snapshot()["running"]:
        return
    install_log_capture()
    rows = load_employee_rows()
    BUS.reset(rows)
    BUS.push_line("[skillpath] Starting 5 Band agents (same as python main.py)...")

    def _on_error(exc: Exception) -> None:
        BUS.set_error(str(exc))

    st.session_state.agents_thread = start_agents_in_background(on_error=_on_error)
    BUS.push_line("[skillpath] Agents running in background. Gap analysis auto-starts in ~10s.")


def _stage_class(current: str, step_key: str) -> str:
    order = [s[0] for s in STAGES]
    if current not in order or step_key not in order:
        return "pipeline-step"
    ci, si = order.index(current), order.index(step_key)
    if ci > si or current == "complete":
        return "pipeline-step done"
    if ci == si:
        return "pipeline-step active"
    return "pipeline-step"


def _render_header() -> None:
    st.markdown(
        """
<div class="skillpath-header">
  <h1>🎓 SkillPath — Enterprise Workforce Reskilling Orchestrator</h1>
  <p>5 AI agents collaborating through Band · Live orchestration dashboard</p>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_pipeline(stage: str) -> None:
    st.markdown("#### Workflow pipeline")
    cols = st.columns(len(STAGES) - 1)
    for col, (key, label) in zip(cols, STAGES[1:]):
        with col:
            st.markdown(
                f'<div class="{_stage_class(stage, key)}">{label}</div>',
                unsafe_allow_html=True,
            )


def _render_metrics(snap: dict) -> None:
    employees = snap["employees"]
    total = len(employees) or 5
    on_track = snap["on_track"] or (total if snap["stage"] == "complete" else 0)
    at_risk = snap["at_risk"]
    avg_weeks = snap["avg_plan_weeks"] or 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-num">{total}</div>'
            f'<div class="metric-lbl">Employees enrolled</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-num">{on_track}</div>'
            f'<div class="metric-lbl">On track this week</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-num">{at_risk}</div>'
            f'<div class="metric-lbl">Need intervention</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        weeks_label = f"{avg_weeks}" if avg_weeks else "—"
        st.markdown(
            f'<div class="metric-card"><div class="metric-num">{weeks_label}</div>'
            f'<div class="metric-lbl">Avg plan length (weeks)</div></div>',
            unsafe_allow_html=True,
        )


def _render_employee_table(snap: dict) -> None:
    st.markdown("#### Employee progress")
    employees = snap["employees"]
    if not employees:
        seed = load_employee_rows()
        employees = {e.name: vars(e) for e in seed}

    if not employees:
        st.info("No employee data found. Add `data/employees.csv`.")
        return

    df = pd.DataFrame(employees.values())
    col_order = [
        "name", "current_role", "target_role", "missing_skills",
        "plan_weeks", "status", "coach_room",
    ]
    for col in col_order:
        if col not in df.columns:
            df[col] = ""
    df = df[col_order]
    df.columns = [
        "Employee", "Current Role", "Target Role", "Skill Gaps",
        "Plan (weeks)", "Status", "Coach Room",
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_activity_log(logs: list[dict]) -> None:
    st.markdown("#### Band agent activity (live)")
    if not logs:
        st.caption("Start the workflow to see live agent messages here.")
        return

    lines = []
    for entry in logs[-80:]:
        agent = entry.get("agent") or "system"
        text = entry.get("text", "")
        kind = entry.get("kind", "info")
        cls = {"handoff": "log-handoff", "escalate": "log-escalate", "success": "log-success"}.get(kind, "")
        display = text.replace(f"[{agent}]", "").strip() if agent != "system" else text
        lines.append(
            f'<div class="{cls}"><span class="agent-tag">[{agent}]</span> {display}</div>'
        )
    st.markdown(f'<div class="log-box">{"".join(lines)}</div>', unsafe_allow_html=True)


def _render_hr_report(snap: dict) -> None:
    st.markdown("#### HR audit report")
    report_path = snap.get("latest_report")
    report = None
    if report_path and Path(report_path).exists():
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    else:
        report = load_latest_hr_report()

    if not report:
        st.caption("Report will appear here when HR Reporter finishes the workflow.")
        return

    st.success(report.get("executive_summary", "Report ready."))
    metrics = report.get("key_metrics", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("On-track %", f"{metrics.get('on_track_percentage', 0)}%")
    m2.metric("Avg skill gaps", metrics.get("average_skill_gaps_per_employee", "—"))
    m3.metric("Est. completion (weeks)", metrics.get("estimated_completion_weeks", "—"))

    with st.expander("Full report JSON"):
        st.json(report)
    if report_path:
        st.caption(f"Saved to `{report_path}`")


# ── Sidebar ───────────────────────────────────────────────────────────────────
_init_session()

with st.sidebar:
    st.markdown("### ⚙️ Controls")
    snap = BUS.snapshot()

    if st.button("▶ Start SkillPath workflow", type="primary", use_container_width=True):
        _start_workflow()
        st.rerun()

    if snap["running"]:
        st.info("Agents are running…")
    elif snap["stage"] == "complete":
        st.success("Workflow complete!")
    elif snap["stage"] == "error":
        st.error(snap.get("error") or "An error occurred.")

    st.markdown("---")
    st.markdown("**How it works**")
    st.markdown(
        "This runs the **same** `python main.py` orchestration:\n"
        "1. Gap Analyst → 2. Curriculum Architect → 3. Coach Agent → "
        "4. Progress Tracker → 5. HR Reporter"
    )
    st.markdown("---")
    st.markdown("**Deploy & share**")
    st.code("streamlit run app.py", language="bash")
    st.caption(
        "For Streamlit Cloud: push to GitHub, connect at share.streamlit.io, "
        "add secrets from `.env` in app Settings → Secrets."
    )

# ── Main layout ───────────────────────────────────────────────────────────────
_render_header()
snap = BUS.snapshot()
_render_pipeline(snap["stage"])
_render_metrics(snap)

tab1, tab2, tab3 = st.tabs(["👥 Employees", "📡 Live activity", "📋 HR report"])

with tab1:
    _render_employee_table(snap)

with tab2:
    _render_activity_log(snap["logs"])
    if snap["running"]:
        st.caption("Auto-refreshing every 2 seconds while agents run…")

with tab3:
    _render_hr_report(snap)

if snap["running"] or snap["stage"] in ("starting", "gap_analysis", "curriculum", "coaching", "tracking", "report"):
    import time
    time.sleep(2)
    st.rerun()
