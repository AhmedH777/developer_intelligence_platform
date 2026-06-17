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

**M3 — controlled patch generation**

- From an approved plan, the model proposes a patch as **search/replace blocks**
  (Aider-style) — it never writes files directly
- Edits are validated before anything touches disk: path safety (no absolute
  paths, no `..` traversal, no protected paths), and each search block must match
  its file **exactly once** (stale/ambiguous edits are rejected)
- The UI shows a **computed unified diff** per file; apply is gated on the safety
  preview
- Apply is **transactional with a snapshot**, so any applied change can be rolled
  back to the exact prior state; the symbol index is refreshed after apply

**M4 — commands & verification**

- A **controlled command runner**: structured `CommandSpec` (never a shell
  string), allowlisted executables only, timeouts, and clean env
- A **persistent job queue** for long-running commands — jobs run as OS
  subprocesses tracked by a `JobService`, survive Streamlit reruns, stream to a
  log file, and are **idempotent** (a rerun/double-click won't launch a duplicate)
- A **verification pipeline** that runs cheapest-first over the files a patch
  changed: Python syntax → ruff → mypy → targeted pytest, with structured,
  persisted results; a missing tool degrades to `NOT_VERIFIED`, not a failure
- **Failed verification blocks completion**: a task with a failing blocking check
  can't be accepted without an explicit, audited override

**M5 — debugging & review**

- A deterministic **traceback parser** extracts frames + the exception; frames
  inside the project root are identified as **repository frames** and their
  source is pulled into context
- **Debug workflow**: ranked hypotheses (with confidence + evidence), suggested
  inspection, a minimal fix, a regression-test idea, and a verification plan —
  all grounded in the parsed frames
- **Review workflow**: structured findings on the latest patch (severity,
  category, file, line range, explanation, recommendation), citing concrete
  files and lines

It does **not** yet include memory/skills or bounded repair — those are later
milestones.

## Architecture

```
ui/   ── Streamlit control plane (thin; calls services only)
dip/  ── UI-agnostic backend package (no Streamlit imports)
  core/         config, Pydantic domain models, ProjectService
  repository/   scanner, ignore rules, AST extraction, search, indexing
  core/         ... + TaskService, JobService (persistent job queue)
  llm/          LLMClient protocol + OpenAI-compatible client, prompts,
                structured-output helper (JSON extraction + validation + repair)
  context/      context compiler (explain / plan / implement evidence selection)
  tools/        safety, patch, diffing, commands, result_parsers,
                traceback_parser
  workflows/    explore, plan, implement, verify, debug, review
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

To make the change: with an approved plan, go to **Changes** → **Generate patch**
→ review the per-file diff → **Apply patch** (snapshotted).

To verify: after applying, open **Tests** → **Run verification** (syntax → lint →
types → targeted tests). If blocking checks pass you can **Accept** on the Changes
page; otherwise accept is blocked (or override explicitly). Use **Execution** to
run an allowlisted command (e.g. the full test suite) as a background job with
live logs.

To review or debug: **Review** runs a structured review of the active task's
latest patch; **Debug** takes a pasted traceback/failure, identifies the
repository frames, and returns ranked hypotheses with a minimal fix.

## Test

```bash
python -m pytest
```

Tests run fully offline — the LLM is mocked, so no model or network is required.
