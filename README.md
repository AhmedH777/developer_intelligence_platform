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

**M6 — memory & skills**

- **Project memory**: durable, source-attributed knowledge (project facts,
  architecture decisions, known failures, preferences, workflow rules) —
  visible, editable, disable-able, and deletable; never stored silently
- **Retrieval into context**: relevant memory is injected into the plan's
  context package (by keyword overlap, with a boost for durable conventions) so
  plans honor established decisions
- **Repository skills**: markdown skill files (`skills/*.md` in the repo) are
  loaded and displayed — human-authored, version-controlled task playbooks

**M7 — architecture checks & bounded repair**

- Imports are indexed; **configurable architecture rules** (e.g. "code under
  `dip/` must not import `streamlit`") are checked project-wide on the
  Architecture page and as a **blocking verification step** on a patch's changed
  files, so violations surface before completion
- **Bounded auto-repair**: when verification fails, a capped loop proposes
  search/replace fixes and re-verifies. Guardrails: a hard attempt cap, a **new
  hypothesis required each attempt**, stop on repeated/oscillating failures,
  protected paths enforced, **scope-expansion and test-weakening require
  approval**, and no dependency installation. Every attempt is snapshotted and
  reversible.

This completes the general-purpose platform (M8 ML/RL extras are optional).

**Enhancements — per-role routing & auto-pilot**

- **Per-role model routing**: each role (planner / coder / reviewer / debugger /
  explainer) can use its own model + temperature, configured under `llm.roles`.
  Unset roles fall back to the base model, so the default is unchanged. This
  squeezes more out of weak local models by matching model→task.
- **Auto-pilot orchestrator**: an opt-in mode that chains plan → patch → apply →
  verify → repair → accept automatically, pausing only at the configured approval
  gates (default: plan and patch). It turns the divided, weak-model-friendly
  workflows into a single autonomous agent without giving up the safety gates.
  Toggle it per task on the Tasks page.

**Enhancements — repo-local data & first-class skills**

- **Repo-local storage**: each registered repo keeps its own data in a gitignored
  `<repo>/.dip/` store (index, tasks, memory, patches, jobs, logs), so an
  agent's knowledge and history travel with the repository. A small cross-repo
  **registry** (`~/.dip/registry.json`, override `DIP_REGISTRY_PATH`) tracks which
  repos are known; the sidebar switches between them.
- **First-class skills**: markdown skills in `<repo>/skills/*.md` are now
  *retrieved by relevance and injected into the planner's context* (not just
  displayed), so they actually shape plans.
- **Per-repo config**: a committed `<repo>/.devintel.yaml` overrides architecture
  rules, allowed commands, safety limits, model roles, auto-pilot gates, or the
  research direction for that repo specifically.

**Research Scout (M8)**

- From a repo's understanding plus a **research direction**, the agent proposes
  ranked, grounded **experiment proposals** (hypothesis, method, which modules to
  touch, variants, evaluation, baselines). Cited modules are checked against the
  index; project memory (known failures / prior findings) and skills inform the
  proposals.
- **Promote a proposal to a Task** → it flows straight into the plan → patch →
  verify pipeline, closing the loop from *idea* to *implemented experiment*.
- Optional **literature grounding** via the public **OpenAlex** API (no key):
  enable `research.literature` to attach relevant papers to the run and let the
  model cite them in `related_work`. Beyond a flat search, it **expands from seed
  papers via their references + citations**, dedupes, and ranks (seeds first, then
  by citation count) for a richer, more relevant neighborhood. Off by default
  (offline); degrades gracefully when the network is restricted.
- A repo configures its direction in `<repo>/.devintel.yaml`:
  ```yaml
  research:
    direction: "improve sample efficiency of residual RL on the driving task"
    objective: "balanced"   # or novelty | feasibility | impact
    literature: true        # ground proposals in OpenAlex papers (needs network)
  ```

## Architecture

```
ui/   ── Streamlit control plane (thin; calls services only)
dip/  ── UI-agnostic backend package (no Streamlit imports)
  core/         config, domain models, ProjectService, TaskService,
                JobService, MemoryService, Registry (cross-repo index)
  repository/   scanner, ignore rules, AST extraction, search, indexing,
                architecture (import-graph rule checks)
  skills/       loader + relevance retrieval for <repo>/skills/*.md playbooks
  llm/          LLMClient protocol + OpenAI-compatible client, router (per-role
                models), prompts, structured-output helper
  workflows/    explore, plan, implement, verify, debug, review, repair,
                orchestrator (auto-pilot), research (experiment scout)
  context/      context compiler (explain / plan / implement evidence selection)
  tools/        safety, patch, diffing, commands, result_parsers,
                traceback_parser
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

Then: **Settings** → register a repository (it creates a gitignored
`<repo>/.dip/` store and indexes immediately) → pick the active repository in the
sidebar → **Repository** → pick a file → pick a symbol → **Explain selected
symbol**. Expand *"Context sent"* to see exactly what the model received. Each
repo's data lives in its own `.dip/`, so switching repos switches all state.

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

To curate knowledge: **Memory** lets you add/edit/disable durable project facts
and decisions (which then inform later plans) and browse repository skill files
under `skills/`.

To find work to do: **Research** → set a direction → **Generate proposals** →
review the ranked experiments → **Promote to task** to implement one.

## Test

```bash
python -m pytest
```

Tests run fully offline — the LLM is mocked, so no model or network is required.
