# Developer Intelligence Platform

An offline, repository-grounded local coding assistant. Deterministic Python
tools handle parsing, search, and persistence; a **local** OpenAI-compatible LLM
(e.g. Qwen-Coder, GPT-OSS via Ollama / LM Studio / llama.cpp) handles reasoning.

This is **Milestone 0 + 1 — the read-only repository assistant**. It can:

- Register a local Python repository
- Scan it (respecting `.gitignore` + default excludes) and extract symbols via AST
- Persist the index to SQLite
- Browse the file tree, view source, and list a file's symbols
- Select a symbol and get a grounded, evidence-linked explanation from a local model
- See **exactly** which source was sent to the model (the context package)

It does **not** yet modify files, run commands, or use background workers — those
are later milestones (see `docs`/the plan). Patch generation, when added, will use
**search/replace blocks** rather than unified diffs.

## Architecture

```
ui/   ── Streamlit control plane (thin; calls services only)
dip/  ── UI-agnostic backend package (no Streamlit imports)
  core/         config, Pydantic domain models, ProjectService
  repository/   scanner, ignore rules, AST extraction, search, indexing
  llm/          LLMClient protocol + OpenAI-compatible client, prompts
  context/      context compiler (what evidence the model sees)
  workflows/    explore workflow (explain a symbol)
  storage/      SQLite schema + typed data-access layer
  container.py  composition root (wires the service graph)
```

The backend never imports a UI framework, so the frontend is swappable.

## Setup

```bash
python -m pip install -e ".[dev]"
```

Configure a local model endpoint (any OpenAI-compatible server) via
`config/settings.yaml` (copy from `config/settings.example.yaml`) or env vars:

```bash
export DIP_LLM_BASE_URL="http://localhost:11434/v1"   # Ollama example
export DIP_LLM_MODEL="qwen2.5-coder"
```

## Run

```bash
streamlit run ui/streamlit_app.py
```

Then: **Settings** → register a repository (it indexes immediately) →
**Repository** → pick a file → pick a symbol → **Explain selected symbol**.
Expand *"Context sent"* to see exactly what the model received.

## Test

```bash
python -m pytest
```

Tests run fully offline — the LLM is mocked, so no model or network is required.
