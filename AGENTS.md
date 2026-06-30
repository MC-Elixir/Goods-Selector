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
- Terminal process running `python main.py agent-web`.
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
python main.py agent-web
```

Open:

```text
http://127.0.0.1:8765
```

The UI can launch new sourcing runs, show preflight health, read previous product selection exports, search candidates, download Excel files, and save product selections to `data/agent_saved_items.json`.
