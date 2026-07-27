# Docker Packaging — Design Spec

Date: 2026-07-07
Branch: dev0.1
Status: Approved (design phase)

## Goal

Package the Amazon Selector pipeline as a Docker image that supports **both** runtime modes:

1. **Long-running agent WebUI** — `docker compose up` starts the local agent console
   (`python main.py agent-web`) on port 8765.
2. **One-shot CLI** — `docker compose run --rm amazon-selector <cmd>` runs any CLI
   subcommand (`init-db`, `run`, `smoke-run`, `seller-sprite-*`, `agent-web`).

Additionally, this is a **formal** deployment: the mock-supplier fallback must be
globally disabled so no fake `SupplierDTO` (`match_verification_method="mock"`) can
ever be emitted by `python main.py run` or the Docker service.

## Context (why the existing Docker packaging is stale)

The repo already has a `Dockerfile`, `.dockerignore`, and `docker-compose.yml`
dated 2026-05-14. Since then:

- The **agent WebUI layer** (`agent/` package, `main.py agent-web` command) was
  added in commit `c790c6c`. The Dockerfile has no `EXPOSE 8765` and its default
  command is `--help`, so the WebUI does not actually run in Docker today.
- The **default Amazon backend** is `crawlers/amazon_scrapling.py` using
  `StealthySession` (Scrapling's patchright-chromium). The Dockerfile only runs
  `playwright install chromium`; it never runs `scrapling install`, so the default
  scraper has no browser in the container.
- The **DB is not bootstrapped on server startup**: `agent/server.py` does not call
  `init_db()`. On a fresh `data/` volume, `docker compose up` would hit
  "no such table" on the first DB-touching API. (`agent/runner.py:82` and
  `smoke_run.py:59` do call `init_db()` before a job, but the server path does not.)
- `alibaba_allow_mock_suppliers` **defaults to True** (`config/settings.py:121`),
  so a plain `python main.py run` silently falls back to mock suppliers when 1688
  is blocked — unacceptable for a formal run.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime modes | Both (server + CLI) | User wants `up` for WebUI and `run` for CLI. |
| Image structure | Single-stage on `python:3.12-slim` | Chromium binaries dominate size (~1.5 GB); multi-stage saves <100 MB and loses in-container `pytest`. Simplest mental model. |
| Browsers | `playwright install chromium` **+** `scrapling install` | Default Amazon scraper (patchright) + 1688 Playwright matcher both need Chromium. `scrapling install` is the missing step. |
| System libs | `python -m playwright install-deps chromium` | Replaces the hand-maintained apt list; robust across Playwright version bumps. |
| Compose shape | One overridable service | `command` defaults to the server; `docker compose run --rm amazon-selector <cli args>` replaces it. Mirrors existing style. |
| Host port binding | `127.0.0.1:8765:8765` | Keeps the CLAUDE.md "local-only by default" ethos. User can drop the prefix to expose remotely. |
| DB bootstrap | `docker-entrypoint.sh` runs `init-db` then `exec`s the real command | `create_all` is idempotent; guarantees tables for both server and CLI on a fresh volume. |
| Mock suppliers | **Globally disabled, code retained** | Flip default `True→False`; hard-set `ALIBABA_ALLOW_MOCK_SUPPLIERS=false` in compose; keep `_mock_suppliers` + `smoke-run --allow-mock` for offline dev/tests. |

## Components

### 1. `Dockerfile` (rewritten, single stage)

```dockerfile
FROM python:3.12-slim

# Chromium system libraries (Playwright-managed, replaces hand-maintained apt list)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl fonts-liberation \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (layered for cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers: playwright chromium (1688 Playwright matcher) + scrapling patchright (default Amazon scraper)
RUN python -m playwright install chromium \
    && scrapling install

# Application code (respects .dockerignore)
COPY . .

# Runtime data dirs (mounted volume overlays these)
RUN mkdir -p /app/data/cache /app/data/exports /app/data/images

# Entrypoint: ensure DB tables exist, then run the requested command
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8765
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["agent-web", "--host", "0.0.0.0", "--port", "8765"]
```

Notes:
- Runs as root (keeps the data-volume story simple; non-root is deferred — see
  Out of Scope). The `data/` host volume is owned by the host user; root inside
  the container can read/write it regardless of host uid.
- `PLAYWRIGHT_BROWSERS_PATH` left at default (`/root/.cache/ms-playwright`); the
  1688 Playwright matcher and scrapling both find their browsers there.

### 2. `docker-entrypoint.sh` (new)

```sh
#!/bin/sh
set -e
# Idempotent: create_all is a no-op when tables already exist.
python main.py init-db || echo "[entrypoint] init-db failed, continuing" >&2
exec python main.py "$@"
```

- `init-db` runs before every container start (server and CLI alike).
- The `|| echo` surfaces a failure (e.g. read-only mount) without blocking the
  whole container on an edge case — the subsequent command will fail loudly on its
  own if the DB is genuinely unusable.

### 3. `docker-compose.yml` (rewritten)

```yaml
services:
  amazon-selector:
    build: .
    image: amazon-selector:dev
    env_file: .env
    environment:
      # Formal deployment: never emit mock suppliers, regardless of .env.
      ALIBABA_ALLOW_MOCK_SUPPLIERS: "false"
    volumes:
      - ./data:/app/data
    ports:
      - "127.0.0.1:8765:8765"   # local-only; drop "127.0.0.1:" prefix to expose remotely
    command: ["agent-web", "--host", "0.0.0.0", "--port", "8765"]
    restart: unless-stopped
```

Usage:
- `docker compose up` → agent WebUI at http://127.0.0.1:8765.
- `docker compose run --rm amazon-selector run --category "Home & Kitchen" --limit 50`
  → CLI pipeline (compose replaces `command`; entrypoint still bootstraps DB).
- `docker compose run --rm amazon-selector pytest tests/ -q` → offline unit tests.

### 4. `.dockerignore` (updated)

Current entries are retained. Add:

```
.venv/
.playwright-mcp/
*.png
dashboard.html
```

The dashboard/test screenshots (~400 KB+ of PNGs) and the standalone `dashboard.html`
draft are not needed at runtime. The `setup_*_login.py` host-side cookie helpers are
left in (harmless; they generate cookies that live in `data/` on the host).

### 5. `.env.example` (new, local-only) + README env reference

There is no `.env.example` today. `.gitignore` (line 29) excludes `.env.example`
alongside `.env`, so the user treats env templates as **local-only** — they are
not committed. Two coordinated artifacts:

**a. Local `.env.example`** (created on the host, gitignored) — a template listing
every key from `config/settings.py` with empty values, for the user to copy to
`.env`:

```dotenv
# ---------- Database ----------
DATABASE_URL=sqlite:///data/amazon_selector.db

# ---------- Vision (PPIO preferred over Anthropic) ----------
PPIO_API_KEY=
PPIO_API_BASE=https://api.ppio.com/openai
PPIO_MODEL=qwen/qwen3.5-plus
PPIO_TEXT_MODEL=zai-org/glm-5.2
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6

# ---------- Amazon ----------
KEEPA_API_KEY=
RAINFOREST_API_KEY=
AMAZON_MARKETPLACE=US

# ---------- 1688 (pifatuan open platform) ----------
ALIBABA_APP_KEY=
ALIBABA_APP_SECRET=
ALIBABA_ACCESS_TOKEN=
# ALIBABA_SUPPLIER_SEARCH_* alias to ALIBABA_PIFATUAN_*; see settings.py

# ---------- SellerSprite (maijiajingling) ----------
MJJL_API_KEY=

# ---------- Behavior ----------
ENABLE_API_CACHE=true
ENABLE_LLM_VERIFICATION=false
ENABLE_SCRAPLING_MATCHER=false
# Formal runs: mock suppliers disabled. Smoke-run --allow-mock still opts in for offline dev.
ALIBABA_ALLOW_MOCK_SUPPLIERS=false
CACHE_TTL_SECONDS=86400
LOG_LEVEL=INFO
```

**b. README Docker section** (tracked) — the canonical, human-readable list of
which env vars are required vs optional, so deployers don't depend on a
gitignored file. `.dockerignore` already excludes the real `.env` from the image.

### 6. Mock disablement (formal-run requirement)

Three changes, no code in `matchers/__init__.py` touched:

1. **`config/settings.py:121`** — flip the default:
   ```python
   alibaba_allow_mock_suppliers: bool = False  # was True; formal runs must never emit mock
   ```
   Effect: plain `python main.py run` (which does not override the flag, unlike
   `smoke-run` / `AgentRuntime`) no longer falls back to mock when 1688 is blocked.
2. **`docker-compose.yml`** — `environment: ALIBABA_ALLOW_MOCK_SUPPLIERS: "false"`
   (in section 3 above). Docker enforces it regardless of the host `.env`.
3. **`.env.example`** — documents the flag (section 5).

Retained:
- `_mock_suppliers()` in `matchers/__init__.py` — still importable / callable.
- `smoke-run --allow-mock` flag and `AgentRuntime` per-job override
  (`agent/runner.py:90-104`, `agent/smoke_run.py:60-82`) — explicit opt-in for
  offline dev/testing.
- All tests that monkeypatch the flag (`test_smoke_run.py`,
  `test_alibaba_result_cache.py`, `test_matchers_manual_queue.py`) — they set the
  flag explicitly, so the default flip does not change their behavior. (To be
  confirmed during implementation for `test_alibaba_result_cache.py`.)

### 7. README — Docker section (new)

Add a short "Docker" section documenting:

```bash
docker compose build
docker compose up                       # agent WebUI at http://127.0.0.1:8765
docker compose run --rm amazon-selector run --category "Home & Kitchen" --limit 50
docker compose run --rm amazon-selector pytest tests/ -q
```

And a one-line note that mock suppliers are disabled by default for formal runs.

## Files to create / modify

| File | Action |
|---|---|
| `Dockerfile` | Rewrite (single stage, add `scrapling install`, `EXPOSE 8765`, entrypoint, server CMD). |
| `docker-entrypoint.sh` | Create. |
| `docker-compose.yml` | Rewrite (server default command, ports, `ALIBABA_ALLOW_MOCK_SUPPLIERS=false`, `restart`). |
| `.dockerignore` | Add `.venv/`, `.playwright-mcp/`, `*.png`, `dashboard.html`. |
| `.env.example` | Create (local-only — gitignored alongside `.env`). |
| `config/settings.py` | Flip `alibaba_allow_mock_suppliers` default `True → False`. |
| `README.md` | Add Docker section (commands + canonical env-var reference, since `.env.example` is not committed). |

## Out of scope (YAGNI for a local tool)

- Multi-stage build / dropping test deps from the final image.
- Non-root user (data-volume host-uid matching is the blocker; deferred).
- Healthcheck on the WebUI port.
- Postgres backend (SQLite + mounted volume is sufficient).
- Deleting the mock code path (retained per decision above).

## Verification plan

1. `docker compose build` — image builds; `scrapling install` and
   `playwright install chromium` both succeed.
2. `docker compose run --rm amazon-selector --help` — prints the click CLI help
   (proves entrypoint + `python main.py` work).
3. `docker compose run --rm amazon-selector pytest tests/ -q` — offline unit
   tests pass green inside the container (proves deps + no env-key requirement).
4. `docker compose up` — server starts; `curl -sI http://127.0.0.1:8765` returns
   200; the WebUI HTML loads. DB file appears at `data/amazon_selector.db` (entrypoint
   ran `init-db`).
5. Mock guard: `docker compose run --rm amazon-selector python -c "from config.settings import settings; assert settings.alibaba_allow_mock_suppliers is False"` — passes.
6. Browser sanity (optional, slow): `docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --limit 1 --skip-preflight` — confirms patchright/playwright Chromium actually launches inside the container. (May fail on 1688 captcha / missing keys — that is expected and not a Docker defect.)

## Risks

- **`scrapling install` correctness**: the command installs "all Scrapling's
  Fetchers dependencies" (verified via `scrapling install --help`). If it does not
  place patchright chromium where `StealthySession` expects, the default Amazon
  scraper will fail at runtime — caught by verification step 6.
- **`test_alibaba_result_cache.py` mock assumption**: if this test relies on the
  *default* being True (rather than monkeypatching), the flip will break it. Fix
  during implementation by making the test set the flag explicitly (consistent with
  the other two mock tests).
- **Root in container**: acceptable for a local tool; documented as a deferred
  hardening item.
