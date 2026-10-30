"""Persistence for project-local roadmap progress."""

import json
import os
import tempfile
from pathlib import Path


PROGRESS_RELATIVE_PATH = Path(".forge") / "roadmap.json"
PROGRESS_VERSION = 1


def load_project_progress(workspace: str | Path) -> dict | None:
    """Load saved roadmap progress, returning None when the project has none."""
    progress_path = Path(workspace) / PROGRESS_RELATIVE_PATH
    try:
        raw = progress_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    try:
        progress = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Saved roadmap is not valid JSON: {error}") from error
    if not isinstance(progress, dict):
        raise ValueError("Saved roadmap must be a JSON object.")
    if type(progress.get("version")) is not int or progress["version"] != PROGRESS_VERSION:
        raise ValueError("Saved roadmap uses an unsupported format version.")
    steps = progress.get("plan_steps", [])
    short_steps = progress.get("short_plan_steps", [])
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ValueError("Saved roadmap steps must be a list.")
    if not isinstance(short_steps, list) or not all(isinstance(step, dict) for step in short_steps):
        raise ValueError("Saved short roadmap steps must be a list.")
    if not isinstance(progress.get("architecture_plan"), (dict, type(None))):
        raise ValueError("Saved architecture plan must be an object or null.")
    if not isinstance(progress.get("project_idea", ""), str):
        raise ValueError("Saved project idea must be text.")
    return progress


def save_project_progress(workspace: str | Path, progress: dict) -> None:
    """Atomically save roadmap progress inside the project directory."""
    progress_path = Path(workspace) / PROGRESS_RELATIVE_PATH
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {**progress, "version": PROGRESS_VERSION},
        ensure_ascii=False,
        indent=2,
    )
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=progress_path.parent,
            prefix=".roadmap-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(payload)
            temporary_file.write("\n")
        os.replace(temporary_path, progress_path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
