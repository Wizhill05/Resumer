"""
crew.py — CrewAI crew definition for the Resume Generator.

Defines agents, tasks, and the crew using the @CrewBase decorator pattern
with YAML configuration files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from crewai import Agent, Crew, Process, Task, LLM  # noqa: E402
from crewai.project import CrewBase, agent, crew, task  # noqa: E402

from schemas.resume_schema import TailoredResume  # noqa: E402
from src.resumer.tools.pdf_tools import compile_pdf  # noqa: E402

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


nim_llm = LLM(
    model="gemini/gemini-3.1-flash-lite-preview",
    api_key=os.environ.get("GEMINI_KEY"),
    temperature=0.7,
    max_tokens=40000,
    top_p=0.9,
)


@CrewBase
class ResumerCrew:
    """Resume Generator Crew — Writer + Critic agents."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    @agent
    def resume_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["resume_writer"],  # type: ignore[index]
            llm=nim_llm,
            tools=[compile_pdf],
            verbose=True,
        )

    @agent
    def resume_shortener(self) -> Agent:
        return Agent(
            config=self.agents_config["resume_shortener"],  # type: ignore[index]
            llm=nim_llm,
            tools=[compile_pdf],
            verbose=True,
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    @task
    def write_resume(self) -> Task:
        return Task(
            config=self.tasks_config["write_resume"],  # type: ignore[index]
            output_pydantic=TailoredResume,
        )

    @task
    def shorten_resume(self) -> Task:
        return Task(
            config=self.tasks_config["shorten_resume"],  # type: ignore[index]
        )

    # ------------------------------------------------------------------
    # Crews
    # ------------------------------------------------------------------

    @crew
    def writing_crew(self) -> Crew:
        """Iteration 1: Writer drafts + compiles."""
        write = self.write_resume()
        return Crew(
            agents=[self.resume_writer()],
            tasks=[write],
            process=Process.sequential,
            verbose=True,
        )

    def shortening_crew(self) -> Crew:
        """Iterations 2+: Shortener trims exactly N lines + compiles."""
        shorten = self.shorten_resume()
        return Crew(
            agents=[self.resume_shortener()],
            tasks=[shorten],
            process=Process.sequential,
            verbose=True,
        )
