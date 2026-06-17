"""Configuration loading for the platform.

Settings come from (in order of precedence): explicit ``DIP_*`` environment
variables, a YAML file (``config/settings.yaml`` by default), then the built-in
defaults below. Keeping this in one place means neither the services nor the UI
hard-code endpoints or paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    "data",
    "checkpoints",
    ".dip",
)


class LLMSettings(BaseModel):
    """Connection details for an OpenAI-compatible local model server."""

    base_url: str = "http://localhost:11434/v1"
    api_key: str = "not-needed-for-local"
    model: str = "qwen2.5-coder"
    temperature: float = 0.1
    max_tokens: int = 1024
    context_char_budget: int = 24000


class Settings(BaseModel):
    """Top-level application settings."""

    storage_dir: Path = Field(default=Path(".dip"))
    llm: LLMSettings = Field(default_factory=LLMSettings)
    default_excludes: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))

    @property
    def database_path(self) -> Path:
        return self.storage_dir / "platform.db"


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Overlay supported ``DIP_*`` environment variables onto loaded YAML data."""

    llm = dict(data.get("llm") or {})
    env_map = {
        "DIP_LLM_BASE_URL": ("base_url", str),
        "DIP_LLM_API_KEY": ("api_key", str),
        "DIP_LLM_MODEL": ("model", str),
        "DIP_LLM_TEMPERATURE": ("temperature", float),
        "DIP_LLM_MAX_TOKENS": ("max_tokens", int),
    }
    for env_name, (key, caster) in env_map.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            llm[key] = caster(raw)
    if llm:
        data["llm"] = llm

    storage = os.environ.get("DIP_STORAGE_DIR")
    if storage:
        data["storage_dir"] = storage
    return data


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Load settings from YAML (if present) with environment overrides applied."""

    data: dict[str, Any] = {}
    path = Path(config_path) if config_path else Path("config/settings.yaml")
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Settings file {path} must contain a YAML mapping.")
        data = loaded

    data = _apply_env_overrides(data)
    return Settings.model_validate(data)
