from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "chrome_profile"
DEFAULT_URL = "https://in.indeed.com/account/login"


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open_chrome_profile",
        description="Open Chrome using the project's persistent chrome_profile for manual login.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Path to browser user data directory (default: chrome_profile)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL to open after browser launch",
    )
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge"],
        default="chrome",
        help="Browser to launch (default: chrome)",
    )
    return parser


def _find_browser_executable(browser: str) -> str:
    candidates: list[Path] = []
    env_roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    if browser == "chrome":
        rel = Path("Google\\Chrome\\Application\\chrome.exe")
        path_hint = shutil.which("chrome.exe")
    else:
        rel = Path("Microsoft\\Edge\\Application\\msedge.exe")
        path_hint = shutil.which("msedge.exe")

    for root in env_roots:
        if root:
            candidates.append(Path(root) / rel)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    if path_hint:
        return path_hint

    raise FileNotFoundError(
        f"Could not find {browser} executable. Install it or pass --browser edge/chrome accordingly."
    )


def _launch_detached(*, executable: str, profile_dir: Path, url: str) -> int:
    cmd = [
        executable,
        f"--user-data-dir={profile_dir}",
        "--new-window",
        url,
    ]
    creationflags = 0
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return proc.pid


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    profile_dir = _resolve_path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Profile directory: {profile_dir}")
    print(f"Target URL: {args.url}")
    print(f"Requested browser: {args.browser}")

    executable = _find_browser_executable(args.browser)
    pid = _launch_detached(executable=executable, profile_dir=profile_dir, url=args.url)
    print(f"Launched browser PID: {pid}")
    print("Browser is detached and will stay open after this script exits.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
