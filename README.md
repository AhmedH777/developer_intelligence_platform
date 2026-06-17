# Developer Intelligence Platform

An offline, repository-grounded local coding assistant. Deterministic Python
tools handle parsing, search, and persistence; a **local** OpenAI-compatible LLM
(e.g. Qwen-Coder, GPT-OSS via Ollama / LM Studio / llama.cpp) handles reasoning.

This currently implements **Milestones 0–2**:

**M0–M1 — read-only repository assistant**

- Register a local Python repository
- Scan it (respecting `.gitignore` + default excludes) and extract symbols via AST
- Persist the index to SQLite
- Browse the file tree, view source, and list a file's symbols
- Select a symbol and get a grounded, evidence-linked explanation from a local model
- See **exactly** which source was sent to the model (the context package)

**M2 — persistent tasks + planning**

- Create a persistent task from a feature request or bug report
- Generate a **structured, grounded implementation plan** (goal, acceptance
  criteria, files to inspect/change, tests, risks, assumptions, open questions)
- Plans are validated against a Pydantic schema with one repair attempt, and
  cited files are checked against the index (hallucinated paths are flagged)
- Approve or reject the plan; every state change and model call is recorded as a
  task event (full audit trail)

It does **not** yet modify files, run commands, or use background workers — those
are later milestones. Patch generation, when added, will use **search/replace
blocks** rather than unified diffs.

## Architecture

```
ui/   ── Streamlit control plane (thin; calls services only)
dip/  ── UI-agnostic backend package (no Streamlit imports)
  core/         config, Pydantic domain models, ProjectService
  repository/   scanner, ignore rules, AST extraction, search, indexing
  core/         ... + TaskService (task state machine + event log)
  llm/          LLMClient protocol + OpenAI-compatible client, prompts,
                structured-output helper (JSON extraction + validation + repair)
  context/      context compiler (explain + plan evidence selection)
  workflows/    explore (explain a symbol), plan (grounded implementation plan)
  storage/      SQLite schema + typed data-access layer
  container.py  composition root (wires the service graph)
```

The backend never imports a UI framework, so the frontend is swappable.

## Setup

```bash
python -m pip install -e ".[dev]"
```

Configure your local model endpoint and API key. The simplest way is a
gitignored `.env` file at the repo root — copy the example and edit it:

```bash
cp .env.example .env
# then edit .env:
#   DIP_LLM_BASE_URL=http://localhost:11434/v1   # Ollama; LM Studio :1234; llama.cpp :8080
#   DIP_LLM_API_KEY=not-needed-for-local
#   DIP_LLM_MODEL=qwen2.5-coder
```

Configuration is read with this precedence (highest first): real `DIP_LLM_*`
environment variables → `.env` file → `config/settings.yaml` (copy from
`config/settings.example.yaml`) → built-in defaults. Use whichever you prefer;
the `.env` file is the recommended place for the URL and key. Changes are picked
up on app restart.

## Run

```bash
streamlit run ui/streamlit_app.py
```

Then: **Settings** → register a repository (it indexes immediately) →
**Repository** → pick a file → pick a symbol → **Explain selected symbol**.
Expand *"Context sent"* to see exactly what the model received.

To plan a change: **Tasks** → *New task* → describe the request → **Generate
plan** → review the plan, its evidence (Context tab), and event history →
**Approve** or **Reject**.

## Test

```bash
python -m pytest
```

Tests run fully offline — the LLM is mocked, so no model or network is required.
