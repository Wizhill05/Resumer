"""
job_hunt_controller.py — Manages parallel, staggered resume generation for bulk job hunting.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from gui.services.runner import ResumeRunController, PipelineStatus
from schemas.indeed_schema import IndeedJob


class JobHuntController:
    """Manages multiple ResumeRunControllers to build resumes in parallel."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.selected_jobs: list[IndeedJob] = []
        self.job_controllers: dict[str, ResumeRunController] = {}
        self.hunting = False
        self._thread: threading.Thread | None = None

    def start_hunt(
        self,
        selected_jobs: list[IndeedJob],
        data_path: str,
        max_iterations: int,
        model: str,
        api_key_env: str,
        omissions: dict[str, bool],
        max_concurrent: int = 2,
    ) -> None:
        if self.hunting:
            raise RuntimeError("Hunt already in progress")

        self.selected_jobs = selected_jobs
        self.hunting = True
        
        # Initialize controllers right away so UI can see them
        for job in selected_jobs:
            if job.job_id not in self.job_controllers:
                self.job_controllers[job.job_id] = ResumeRunController(self.workspace_root)

        self._thread = threading.Thread(
            target=self._hunt_worker,
            args=(data_path, max_iterations, model, api_key_env, omissions, max_concurrent),
            daemon=True,
        )
        self._thread.start()

    def stop_hunt(self) -> None:
        self.hunting = False
        for controller in self.job_controllers.values():
            controller.stop_run()

    def poll_all(self) -> None:
        """Called by the Streamlit UI to drain logs and update status for all controllers."""
        for controller in self.job_controllers.values():
            controller.poll()
            
        # Check if any are still running
        if self.hunting:
            any_running = any(c.is_running() for c in self.job_controllers.values())
            # Note: the worker thread itself might still be launching them.
            # We rely on the worker thread to set self.hunting = False when completely done.

    def get_controller(self, job_id: str) -> ResumeRunController | None:
        return self.job_controllers.get(job_id)

    def _hunt_worker(
        self,
        data_path: str,
        max_iterations: int,
        model: str,
        api_key_env: str,
        omissions: dict[str, bool],
        max_concurrent: int,
    ) -> None:
        for i, job in enumerate(self.selected_jobs):
            if not self.hunting:
                break

            # Block until we have an open slot
            while self.hunting:
                active_count = sum(1 for c in self.job_controllers.values() if c.is_running())
                if active_count < max_concurrent:
                    break
                time.sleep(2)
                
            if not self.hunting:
                break

            controller = self.job_controllers[job.job_id]
            
            # Clean up job title for folder name
            job_label = "".join(c if c.isalnum() else "_" for c in job.company).strip("_").lower()[:30]
            if not job_label:
                job_label = job.job_id

            # Use description if we fetched it, else snippet
            jd_text = job.description if job.description else job.snippet
            
            try:
                controller.start_run(
                    jd_text=jd_text,
                    data_path=data_path,
                    max_iterations=max_iterations,
                    job_label=f"indeed_{job_label}_{job.job_id}",
                    model=model,
                    api_key_env=api_key_env,
                    omissions=omissions,
                    url="",  # Pass empty URL so main.py uses the text and avoids re-scraping
                )
            except Exception as e:
                import sys
                print(f"Error starting run for job {job.job_id}: {e}", file=sys.stderr)
                controller.status.state = "failed"
                controller.status.active_task = f"Failed to start: {e}"

            # Stagger starts by 5 seconds
            if i < len(self.selected_jobs) - 1:
                time.sleep(5)

        # Wait for all runs to finish
        while self.hunting:
            all_done = True
            for controller in self.job_controllers.values():
                if controller.is_running():
                    all_done = False
                    break
            
            if all_done:
                self.hunting = False
                break
            time.sleep(1)
