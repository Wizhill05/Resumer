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

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


# Monkey-patch LiteLLM Cloudflare Chat transformer to fix spelling error in headers
# LiteLLM v1.83.0 has a typo: "content-type": "apbplication/json" which causes Cloudflare API 10000 Authentication Error.
# Also patch transform_response to support standard OpenAI-like or text response formats from different Cloudflare AI models (like kimi-k2.6) and avoid KeyError: 'response'.
try:
    import litellm.llms.cloudflare.chat.transformation as t
    _original_validate = t.CloudflareChatConfig.validate_environment
    _original_transform = t.CloudflareChatConfig.transform_response

    def _patched_validate(self, headers, model, messages, optional_params, litellm_params, api_key=None, api_base=None):
        headers = _original_validate(self, headers, model, messages, optional_params, litellm_params, api_key, api_base)
        if headers.get("content-type") == "apbplication/json":
            headers["content-type"] = "application/json"
        return headers

    def _patched_transform(self, model, raw_response, model_response, logging_obj, request_data, messages, optional_params, litellm_params, encoding, api_key=None, json_mode=None):
        try:
            completion_response = raw_response.json()
        except Exception:
            return _original_transform(self, model, raw_response, model_response, logging_obj, request_data, messages, optional_params, litellm_params, encoding, api_key, json_mode)

        content = None
        if isinstance(completion_response, dict):
            res_obj = completion_response.get("result")
            if isinstance(res_obj, dict):
                if "response" in res_obj:
                    content = res_obj["response"]
                elif "text" in res_obj:
                    content = res_obj["text"]
                elif "choices" in res_obj and isinstance(res_obj["choices"], list) and len(res_obj["choices"]) > 0:
                    choice = res_obj["choices"][0]
                    if isinstance(choice, dict):
                        if "message" in choice and isinstance(choice["message"], dict):
                            content = choice["message"].get("content")
                        elif "text" in choice:
                            content = choice.get("text")
            elif isinstance(res_obj, str):
                content = res_obj
            
            if content is None and "choices" in completion_response and isinstance(completion_response["choices"], list) and len(completion_response["choices"]) > 0:
                choice = completion_response["choices"][0]
                if isinstance(choice, dict):
                    if "message" in choice and isinstance(choice["message"], dict):
                        content = choice["message"].get("content")
                    elif "text" in choice:
                        content = choice.get("text")
                        
        if content is not None:
            model_response.choices[0].message.content = content
            try:
                import time
                from litellm.types.utils import Usage
                import litellm
                prompt_tokens = litellm.utils.get_token_count(messages=messages, model=model)
                completion_tokens = len(encoding.encode(content))
                model_response.created = int(time.time())
                model_response.model = "cloudflare/" + model
                model_response.usage = Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                )
            except Exception:
                pass
            return model_response
            
        return _original_transform(self, model, raw_response, model_response, logging_obj, request_data, messages, optional_params, litellm_params, encoding, api_key, json_mode)

    t.CloudflareChatConfig.validate_environment = _patched_validate
    t.CloudflareChatConfig.transform_response = _patched_transform
except Exception:
    pass


_DEFAULT_MODEL = "mistral/mistral-large-latest"


def resolve_llm_runtime() -> tuple[str, str, str | None]:
    """Resolve model name and matching API key env var for runtime."""
    model = (os.environ.get("RESUMER_MODEL") or _DEFAULT_MODEL).strip()

    # Map raw @cf/ prefix to cloudflare/@cf/ so LiteLLM resolves it properly
    if model.startswith("@cf/"):
        model = f"cloudflare/{model}"

    key_env = (os.environ.get("RESUMER_API_KEY_ENV") or "").strip()

    if not key_env:
        model_prefix_to_env = (
            ("mistral/", "MISTRAL_API_KEY"),
            ("gemini/", "GEMINI_KEY"),
            ("google/", "GEMINI_KEY"),
            ("openrouter/", "OPENROUTER_API_KEY"),
            ("groq/", "GROQ_API_KEY"),
            ("qwen/", "GROQ_API_KEY"),
            ("anthropic/", "ANTHROPIC_API_KEY"),
            ("openai/", "OPENAI_API_KEY"),
            ("cloudflare/", "CLOUDFLARE_AUTH_TOKEN"),
        )
        for prefix, env_name in model_prefix_to_env:
            if model.startswith(prefix):
                key_env = env_name
                break

    if not key_env:
        key_env = "MISTRAL_API_KEY"

    # Support fallback to CLOUDFLARE_API_KEY if CLOUDFLARE_AUTH_TOKEN is requested but not found
    api_key = os.environ.get(key_env)
    if key_env == "CLOUDFLARE_AUTH_TOKEN" and not api_key:
        api_key = os.environ.get("CLOUDFLARE_API_KEY")
        if api_key:
            key_env = "CLOUDFLARE_API_KEY"

    # LiteLLM expects CLOUDFLARE_API_KEY in env variables for Cloudflare provider.
    # Set CLOUDFLARE_API_KEY and CLOUDFLARE_AUTH_TOKEN to ensure they are synchronized.
    if model.startswith("cloudflare/"):
        if not api_key:
            api_key = os.environ.get("CLOUDFLARE_API_KEY")
        if api_key:
            if "CLOUDFLARE_API_KEY" not in os.environ:
                os.environ["CLOUDFLARE_API_KEY"] = api_key
            if "CLOUDFLARE_AUTH_TOKEN" not in os.environ:
                os.environ["CLOUDFLARE_AUTH_TOKEN"] = api_key

        if "CLOUDFLARE_ACCOUNT_ID" not in os.environ:
            raise ValueError(
                "CLOUDFLARE_ACCOUNT_ID environment variable is missing. "
                "Please add CLOUDFLARE_ACCOUNT_ID to your .env.local file to use Cloudflare models."
            )

    return model, key_env, api_key


_nim_llm: LLM | None = None


def _normalize_anthropic_base_url(model: str, api_base: str) -> str:
    """Strip /v1 or /v1/messages suffix for anthropic/ models.

    LiteLLM's Anthropic handler auto-appends /v1/messages to the base URL.
    If the user already included /v1 in their URL, the result would be
    /v1/v1/messages (404). Strip it so LiteLLM constructs the correct path.
    """
    if model.startswith("anthropic/"):
        api_base = api_base.rstrip("/")
        if api_base.endswith("/v1/messages"):
            api_base = api_base[: -len("/v1/messages")]
        elif api_base.endswith("/v1"):
            api_base = api_base[: -len("/v1")]
    return api_base


def get_llm() -> LLM:
    """Lazy loader for the LLM to prevent early initialization during static module imports."""
    global _nim_llm
    if _nim_llm is None:
        model, key_env, api_key = resolve_llm_runtime()
        api_base = (os.environ.get("RESUMER_API_BASE") or "").strip()

        llm_kwargs = {
            "model": model,
            "api_key": api_key,
            "temperature": 0.7,
            "max_tokens": 40000,
            "top_p": 0.9,
        }
        if api_base:
            llm_kwargs["base_url"] = _normalize_anthropic_base_url(model, api_base)

        _nim_llm = LLM(**llm_kwargs)
    return _nim_llm


@CrewBase
class ResumerCrew:
    """Resume Generator Crew — Writer + Critic agents."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    @agent
    def job_analyzer(self) -> Agent:
        return Agent(
            config=self.agents_config["job_analyzer"],  # type: ignore[index]
            llm=get_llm(),
            verbose=False,
        )

    @agent
    def summary_skills_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["summary_skills_writer"],  # type: ignore[index]
            llm=get_llm(),
            verbose=False,
        )

    @agent
    def projects_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["projects_writer"],  # type: ignore[index]
            llm=get_llm(),
            verbose=False,
        )

    @agent
    def experience_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["experience_writer"],  # type: ignore[index]
            llm=get_llm(),
            verbose=False,
        )

    @agent
    def resume_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["resume_writer"],  # type: ignore[index]
            llm=get_llm(),
            verbose=False,
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    @task
    def analyze_job(self) -> Task:
        return Task(
            config=self.tasks_config["analyze_job"],  # type: ignore[index]
        )

    @task
    def write_summary_skills(self) -> Task:
        return Task(
            config=self.tasks_config["write_summary_skills"],  # type: ignore[index]
        )

    @task
    def write_projects_section(self) -> Task:
        return Task(
            config=self.tasks_config["write_projects_section"],  # type: ignore[index]
        )

    @task
    def write_experience_section(self) -> Task:
        return Task(
            config=self.tasks_config["write_experience_section"],  # type: ignore[index]
        )

    @task
    def write_resume(self) -> Task:
        return Task(
            config=self.tasks_config["write_resume"],  # type: ignore[index]
        )

    # ------------------------------------------------------------------
    # Crews
    # ------------------------------------------------------------------

    @crew
    def job_analysis_crew(self) -> Crew:
        analyze = self.analyze_job()
        return Crew(
            agents=[self.job_analyzer()],
            tasks=[analyze],
            process=Process.sequential,
            verbose=False,
        )

    @crew
    def summary_skills_crew(self) -> Crew:
        write = self.write_summary_skills()
        return Crew(
            agents=[self.summary_skills_writer()],
            tasks=[write],
            process=Process.sequential,
            verbose=False,
        )

    @crew
    def projects_crew(self) -> Crew:
        write = self.write_projects_section()
        return Crew(
            agents=[self.projects_writer()],
            tasks=[write],
            process=Process.sequential,
            verbose=False,
        )

    @crew
    def experience_crew(self) -> Crew:
        write = self.write_experience_section()
        return Crew(
            agents=[self.experience_writer()],
            tasks=[write],
            process=Process.sequential,
            verbose=False,
        )

    @crew
    def writing_crew(self) -> Crew:
        """Iteration 1: Writer drafts + compiles."""
        write = self.write_resume()
        return Crew(
            agents=[self.resume_writer()],
            tasks=[write],
            process=Process.sequential,
            verbose=False,
        )
