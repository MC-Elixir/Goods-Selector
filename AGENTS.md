# AGENTS.md

This file defines general agent design principles for this repository.

## Agent Design Principle

An agent is a model using tools in a loop.

Every agent must be defined by three core components:

1. Environment
   - The runtime context the agent can observe and operate in.
   - Examples: repository, terminal, filesystem, browser, VM, Kubernetes cluster, database, APIs.

2. Tools
   - The actions the agent is allowed to take in the environment.
   - Examples: bash, grep, read, write, edit, test, search, fetch, screenshot, kubectl, git.

3. System Prompt
   - The goals, constraints, behavior rules, and decision policy of the agent.
   - It defines what the agent is trying to do, how it should act, and what it must avoid.

The agent should operate as a loop:

```python
env = Environment()
tools = Tools(env)
system_prompt = "Goals, constraints, and how to act"

while True:
    action = llm.run(system_prompt + env.state)
    env.state = tools.run(action)
```

## Amazon Selector Agent

This repository implements the principle above as a local product sourcing agent.

### Environment

- Repository code and configuration.
- Terminal process running `docker compose up -d --build amazon-selector` for the official WebUI runtime.
- SQLite database at `data/amazon_selector.db`.
- Cookie files in `data/amazon_cookies.json` and `data/1688_cookies.json`.
- Exported result files in `data/exports/`.
- Amazon and 1688 browser sessions, including human-in-the-loop captcha or popup handling.

### Tools

- `agent.preflight.run_preflight()` checks whether the environment is ready.
- `pipeline.orchestrator.run_pipeline()` runs the 7-stage sourcing workflow.
- `agent.history` reads previous JSON/Excel exports and stores saved selections.
- `agent.server` exposes local JSON APIs and static WebUI assets.

### System Prompt

The runtime prompt is stored in `agent.runner.AGENT_SYSTEM_PROMPT`.

Policy summary:

- Prefer real Amazon and real 1688 data over mock data.
- In formal no-mock mode, do not allow mock suppliers into results.
- Run preflight before starting sourcing work.
- If 1688 is blocked by login, popup, or captcha, stop and ask for human action.
- Audit exports after each run before presenting candidates.

### Local WebUI

Run:

```bash
docker compose up -d --build amazon-selector
```

Open:

```text
http://127.0.0.1:8765
```

`python main.py agent-web` remains available only for local debugging fallback.

The UI can launch new sourcing runs, show preflight health, read previous product selection exports, search candidates, download Excel files, and save product selections to `data/agent_saved_items.json`.

## Cursor Cloud specific instructions

This environment runs the project directly on the VM (not via Docker). Standard commands live in `README.md` / `CLAUDE.md`; the notes below only capture non-obvious, durable caveats.

- Python runs in a `.venv` virtualenv at the repo root. Run everything through it, e.g. `.venv/bin/python main.py ...`, `.venv/bin/python -m pytest tests/`, `.venv/bin/python -m benchmarks.evaluate_target_contract`. The startup update script keeps `.venv` in sync with `requirements.txt`.
- System-level dependencies are baked into the environment image (not reinstalled by the update script): `python3.12-venv`, `python3-dev`, and the Playwright/Chromium runtime libraries (`playwright install-deps chromium`, which needs root). Reinstall these with `sudo apt-get install` only if a fresh base VM is ever missing them.
- Two Chromium engines are used and both are installed as browser binaries (no root needed): Playwright Chromium (1688 matcher) via `.venv/bin/python -m playwright install chromium`, and patchright Chromium (the default Scrapling Amazon scraper) via `.venv/bin/patchright install chromium`. If a run errors with "Executable doesn't exist at .../chromium-*/chrome", the patchright browser is what is missing.
- Automated tests: `.venv/bin/python -m pytest tests/` runs fully offline with no secrets. Two tests fail on a clean checkout because they read local-only, git-ignored files that do not exist in a fresh clone: `test_docker_deployment.py` reads `.env.example`, and `test_target_contract_benchmark.py` reads a `data/exports/candidates_*.json` fixture. These are environment/fixture gaps, not code regressions.
- Live sourcing: the Amazon BSR crawl (pipeline stage 1) works with no API key or cookies. The 1688 supplier-match stage needs user secrets — `PPIO_API_KEY` (or `ANTHROPIC_API_KEY`) for vision keywords plus `data/1688_cookies.json` — otherwise it returns 0 candidates. Image-based 1688 search without cookies hits a TMD captcha, which opens a ~900s circuit-breaker cooldown that also blocks later runs; `smoke-run --allow-mock` does not bypass that captcha block.
- Fully-offline end-to-end core action (no secrets): the Market Research / seller-shortlist feature. Place a SellerSprite competitor export CSV under `data/imports/` and run `.venv/bin/python main.py seller-research --file <name>.csv --category patio_heater --no-ai`, or use the WebUI "Market Research" tab. It produces a ranked shortlist plus Excel/JSON in `data/exports/`.
