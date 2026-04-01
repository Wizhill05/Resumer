"""
Pydantic v2 schemas for the structured LLM output.

The LLM fills these models; education & personal info come directly from truth.json.
"""

from pydantic import BaseModel, Field


class SkillCategory(BaseModel):
    """A group of related skills under a named category."""

    category: str = Field(
        description="Category name, e.g. 'Programming Languages', 'AI & ML'"
    )
    items: list[str] = Field(description="List of skills in this category")


class TailoredProject(BaseModel):
    """A project selected and tailored for the target job."""

    name: str = Field(description="Project name")
    tech_stack: str = Field(
        description="Comma-separated technologies, e.g. 'Python, FastAPI, PostgreSQL'"
    )
    link: str | None = Field(
        default=None,
        description="The URL for the project, if available in the profile. Always start with https://"
    )
    bullets: list[str] = Field(
        description="2-3 concise, quantified bullet points tailored to the job"
    )


class TailoredExperience(BaseModel):
    """A work experience entry tailored for the target job."""

    role: str = Field(description="Job title / role name")
    organization: str = Field(description="Company or organization name")
    location: str = Field(description="City, State or 'Remote'")
    duration: str = Field(description="Date range, e.g. 'Jan 2024 - Present'")
    bullets: list[str] = Field(
        description="2-3 concise, quantified bullet points tailored to the job"
    )


class ActivityGroup(BaseModel):
    """A group of extra-curricular activities or leadership roles under a specific topic."""

    topic: str = Field(description="Topic name, e.g. 'Leadership', 'Teamwork'")
    bullets: list[str] = Field(
        description="List of concise bullet points or achievements for this topic"
    )


class TailoredResume(BaseModel):
    """
    The complete structured resume body that the LLM must produce.

    Does NOT include education or personal info -- those are injected
    from the master profile by the Jinja2 template.
    """

    applying_for: str | None = Field(
        default=None,
        description="The job title being applied for, e.g. 'Software Engineer'",
    )
    objective: str | None = Field(
        default=None,
        description="1-2 sentence tailored career objective for this specific role",
    )
    skills: list[SkillCategory] | None = Field(
        default=None,
        description=(
            "Skills grouped by category (2-4 categories). "
            "Select only skills relevant to the target job."
        ),
    )
    projects: list[TailoredProject] | None = Field(
        default=None, description="2/3 projects most relevant to the target job"
    )
    experience: list[TailoredExperience] | None = Field(
        default=None,
        description="Work experience entries (0 or more), most recent first",
    )
    activities: list[ActivityGroup] | None = Field(
        default=None,
        description="Extra-Curricular Activities & Leadership grouped by topic",
    )
