"""
main.py — SkillPath Entry Point
Starts all 5 agents concurrently. Each agent connects to Band independently
and communicates through Band rooms.

Usage:
    python main.py
    streamlit run app.py   # same agents + live dashboard UI
"""

import asyncio
from rich.console import Console
from rich.panel   import Panel

from run_agents import run_all_agents

console = Console()


async def main():
    console.print(Panel.fit(
        "[bold cyan]SkillPath — Enterprise Workforce Reskilling Orchestrator[/bold cyan]\n"
        "[dim]5 AI agents collaborating through Band[/dim]",
        border_style="cyan"
    ))

    console.print("\n[green]Starting all agents...[/green]")
    await run_all_agents()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stopped by user]")
