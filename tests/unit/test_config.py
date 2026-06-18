from __future__ import annotations

from pathlib import Path

from dip.core.config import load_settings, parse_dotenv


def test_parse_dotenv_handles_comments_quotes_and_export() -> None:
    text = (
        "# a comment\n"
        "\n"
        "DIP_LLM_BASE_URL=http://localhost:1234/v1\n"
        'export DIP_LLM_API_KEY="secret-key"\n'
        "DIP_LLM_MODEL='qwen2.5-coder'\n"
        "MALFORMED_LINE_NO_EQUALS\n"
    )
    values = parse_dotenv(text)
    assert values["DIP_LLM_BASE_URL"] == "http://localhost:1234/v1"
    assert values["DIP_LLM_API_KEY"] == "secret-key"
    assert values["DIP_LLM_MODEL"] == "qwen2.5-coder"
    assert "MALFORMED_LINE_NO_EQUALS" not in values


def test_load_settings_reads_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DIP_LLM_BASE_URL=http://example:9999/v1\n"
        "DIP_LLM_API_KEY=from-dotenv\n"
        "DIP_LLM_MODEL=my-model\n",
        encoding="utf-8",
    )
    settings = load_settings(config_path=tmp_path / "missing.yaml", dotenv_path=env_file)
    assert settings.llm.base_url == "http://example:9999/v1"
    assert settings.llm.api_key == "from-dotenv"
    assert settings.llm.model == "my-model"


def test_real_env_var_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DIP_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("DIP_LLM_MODEL", "from-process-env")
    settings = load_settings(config_path=tmp_path / "missing.yaml", dotenv_path=env_file)
    assert settings.llm.model == "from-process-env"


def test_missing_dotenv_is_fine(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.yaml", dotenv_path=tmp_path / ".env"
    )
    # Falls back to built-in defaults.
    assert settings.llm.model == "qwen2.5-coder"
