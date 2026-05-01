"""Typed loading for `.ces/config.yaml` with legacy-compatible dict output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    project_name: str | None = None
    preferred_runtime: str | None = None
    execution_mode: Literal["local"] = "local"
    version: str | None = None
    created_at: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> ProjectConfig:
        execution_mode = raw.get("execution_mode", "local")
        if execution_mode != "local":
            raise ValueError(f"unsupported execution_mode: {execution_mode}")
        project_id = raw.get("project_id", "default")
        if not isinstance(project_id, str):
            raise ValueError("project_id must be a string")
        return cls(
            project_id=project_id,
            project_name=_optional_str(raw.get("project_name")),
            preferred_runtime=_optional_str(raw.get("preferred_runtime")),
            execution_mode="local",
            version=_optional_str(raw.get("version")),
            created_at=_optional_str(raw.get("created_at")),
        )


_MODEL_KEYS = {
    "project_id",
    "project_name",
    "preferred_runtime",
    "execution_mode",
    "version",
    "created_at",
}


def load_project_config_dict(config_path: Path) -> dict[str, Any]:
    """Load config through ``ProjectConfig`` while preserving dict compatibility."""
    if not config_path.is_file():
        return {}
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("execution_mode") == "server":
        # Preserve the legacy value so reject_server_mode() can raise the
        # explicit local-first migration error instead of treating it as corrupt.
        return raw
    try:
        model = ProjectConfig.from_mapping(raw)
    except ValueError:
        return {}

    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _MODEL_KEYS:
            normalized[key] = getattr(model, key)
        else:
            normalized[key] = value
    return normalized


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected string or null")
    return value
