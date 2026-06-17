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


class SafetySettings(BaseModel):
    """Guardrails for patch application (the plan's §18 configuration)."""

    require_patch_approval: bool = True
    max_modified_files: int = 8
    protected_paths: list[str] = Field(
        default_factory=lambda: [".git", ".env", "secrets"]
    )


class CommandSettings(BaseModel):
    """Controlled-execution policy (the plan's §15.2)."""

    allowed_executables: list[str] = Field(
        default_factory=lambda: ["python", "python3", "pytest", "ruff", "mypy", "pyright"]
    )
    default_timeout_seconds: int = 300
    # Block automatic task completion when verification fails.
    block_completion_on_failed_verification: bool = True


class Settings(BaseModel):
    """Top-level application settings."""

    storage_dir: Path = Field(default=Path(".dip"))
    llm: LLMSettings = Field(default_factory=LLMSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    commands: CommandSettings = Field(default_factory=CommandSettings)
    default_excludes: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))

    @property
    def database_path(self) -> Path:
        return self.storage_dir / "platform.db"


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse a minimal ``.env`` file (``KEY=VALUE`` lines).

    Supports ``#`` comments, blank lines, an optional ``export`` prefix, and
    single/double quoted values. Intentionally dependency-free so the platform
    stays installable offline.
    """

    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (len(value) >= 2) and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _load_dotenv(path: Path) -> dict[str, str]:
    if path.exists():
        return parse_dotenv(path.read_text(encoding="utf-8"))
    return {}


def _apply_env_overrides(data: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """Overlay supported ``DIP_*`` variables (from ``env``) onto loaded YAML data."""

    llm = dict(data.get("llm") or {})
    env_map = {
        "DIP_LLM_BASE_URL": ("base_url", str),
        "DIP_LLM_API_KEY": ("api_key", str),
        "DIP_LLM_MODEL": ("model", str),
        "DIP_LLM_TEMPERATURE": ("temperature", float),
        "DIP_LLM_MAX_TOKENS": ("max_tokens", int),
    }
    for env_name, (key, caster) in env_map.items():
        raw = env.get(env_name)
        if raw is not None and raw != "":
            llm[key] = caster(raw)
    if llm:
        data["llm"] = llm

    storage = env.get("DIP_STORAGE_DIR")
    if storage:
        data["storage_dir"] = storage
    return data


def load_settings(
    config_path: Path | str | None = None,
    dotenv_path: Path | str | None = None,
) -> Settings:
    """Load settings from YAML + ``.env``, with process env vars taking precedence.

    Precedence (highest first): real ``DIP_*`` environment variables, ``.env``
    file, ``config/settings.yaml``, built-in defaults. This lets you keep the
    endpoint URL and API key in a gitignored ``.env`` file at the repo root.
    """

    data: dict[str, Any] = {}
    path = Path(config_path) if config_path else Path("config/settings.yaml")
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Settings file {path} must contain a YAML mapping.")
        data = loaded

    dotenv = _load_dotenv(Path(dotenv_path) if dotenv_path else Path(".env"))
    # Real environment variables win over the .env file.
    env = {**dotenv, **os.environ}

    data = _apply_env_overrides(data, env)
    return Settings.model_validate(data)
