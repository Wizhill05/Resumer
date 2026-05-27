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
    project_summary: str | None = Field(
        default=None,
        description="A 2-4 word project summary for the rendered heading.",
    )
    completion_time: str | None = Field(
        default=None,
        description="Concise completion time shown on the right side of the project heading.",
    )
    link: str | None = Field(
        default=None,
        description="The URL for the project, if available in the profile. Always start with https://. If unavailable, keep it empty.",
    )
    github_path: str | None = Field(
        default=None,
        description="The GitHub username and repository name, e.g. 'Wizhill05/LauchYourLLM' extracted from the project link. If not a GitHub link, leave as None.",
    )
    points: list[str] = Field(
        description="Exactly 3 concise unordered project points, each starting with an action verb."
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
    """A group of extra-curricular activities or achievements under a specific topic."""

    topic: str = Field(
        description="Topic name, e.g. 'Achievements', 'Activities', 'Public Speaking'"
    )
    bullets: list[str] = Field(
        description="List of concise bullet points or achievements for this topic"
    )


class JobAnalysis(BaseModel):
    """Structured analysis of a noisy job description."""

    cleaned_job_desc: str = Field(
        description="Clean, concise version of the job description without scraped-page noise"
    )
    applying_for: str | None = Field(
        default=None,
        description="Short role phrase, e.g. 'Software Developer' or 'AI Engineer Intern'",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description="Top required skills from the JD. Keep this to at most 10 items.",
    )
    preferred_skills: list[str] = Field(
        default_factory=list,
        description="Useful skills and keywords that are helpful but not top requirements.",
    )
    key_responsibilities: list[str] = Field(
        default_factory=list,
        description="Main responsibilities extracted from the JD.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="ATS keywords and exact phrases from the JD.",
    )
    experience_years: int | None = Field(
        default=None,
        description="Years of experience requested by the JD, if explicit.",
    )
    seniority_level: str | None = Field(
        default=None,
        description="intern, junior, mid, senior, lead, manager, or unknown.",
    )


class SummarySkillsDraft(BaseModel):
    """Resume professional summary, skills section, and extracurricular achievements draft."""

    professional_summary: str = Field(
        description="Formal 1-2 line professional summary tailored to the job."
    )
    skills: list[SkillCategory] = Field(
        description="Job-specific skill categories. Must include a Soft Skills category and contain exactly 15 individual skills in total, tightly focused on the target job description."
    )
    extra_curricular: list[str] = Field(
        default_factory=list,
        description="List of concise extracurricular achievements or activities."
    )


class SectionProject(BaseModel):
    """Intermediate project entry produced by the section writer."""

    name: str = Field(description="Project name")
    project_summary: str | None = Field(
        default=None,
        description="A 2-4 word project summary for the rendered heading.",
    )
    completion_time: str | None = Field(
        default=None,
        description="Concise completion time shown on the right side of the rendered heading.",
    )
    link: str | None = Field(
        default=None,
        description='Project link copied exactly from candidate profile when available. For newly introduced projects, use "".',
    )
    domain: str | None = Field(
        default=None,
        description="Optional project domain, e.g. AI Automation or Backend Systems.",
    )
    description: str | None = Field(
        default=None,
        description="Legacy fallback text for extracting project points when provided.",
    )
    points: list[str] = Field(
        description="Exactly 3 concise unordered project points with action verbs and numeric data.",
    )


class SectionExperience(BaseModel):
    """Intermediate work experience entry produced by the section writer."""

    role: str = Field(description="Role/title")
    time_period: str = Field(description="Date range")
    company_name: str = Field(description="Company or organization name")
    location: str = Field(description="Location")
    points: list[str] = Field(description="Resume bullet points")


class ProjectsDraft(BaseModel):
    """Projects section draft."""

    projects: dict[str, SectionProject] = Field(default_factory=dict)


class ExperienceDraft(BaseModel):
    """Work experience section draft."""

    work_experience: dict[str, SectionExperience] = Field(default_factory=dict)


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
        description='1-2 lines PROFESSIONAL SUMMARY explaining why you are a good fit. Example: "Experienced Project Focused Software engineering student seeking full time Front end development"',
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
        description="Extra-Curricular Activities & Achievements grouped by topic",
    )
