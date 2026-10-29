"""JSON export of a dataset profile (EDA-05)."""

from __future__ import annotations

from pathlib import Path

from ..models import DatasetProfile


def profile_to_json(profile: DatasetProfile) -> str:
    """Serialise *profile* as indented JSON with a trailing newline and stable key order."""
    return profile.model_dump_json(indent=2) + "\n"


def write_profile_json(profile: DatasetProfile, path: Path) -> None:
    """Write the JSON export to *path* (UTF-8, LF line endings)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile_to_json(profile), encoding="utf-8", newline="\n")
