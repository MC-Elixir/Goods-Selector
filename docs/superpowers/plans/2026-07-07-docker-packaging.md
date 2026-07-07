# Docker Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the Amazon Selector pipeline as a single Docker image that runs the agent WebUI (`docker compose up`) and one-shot CLI jobs (`docker compose run --rm amazon-selector <cmd>`), with mock suppliers globally disabled for formal runs.

**Architecture:** Single-stage image on `python:3.12-slim` installing both `playwright chromium` and `scrapling` (patchright) browsers, plus a `docker-entrypoint.sh` that bootstraps the SQLite DB before every start. One overridable compose service whose default `command` is the server; CLI invocations replace it. The mock-supplier default is flipped `True→False` in `config/settings.py` and hard-set `false` in compose env.

**Tech Stack:** Docker, Docker Compose v2, Python 3.12, Playwright, Scrapling/patchright, pydantic-settings, click, SQLAlchemy/SQLite.

## Global Constraints

- All commands run from the `amazon_selector/` repo root (the git root).
- Base image is `python:3.12-slim` — do not change to 3.13.
- Unit tests run offline with mock DTOs — no network, no API keys, no `.env` required.
- **Docker is NOT installed in the current WSL2 distro** (`docker: command not found`). Tasks 1–5 (file authoring + unit test) are fully executable here. Task 6 (build & verify) requires Docker — either enable Docker Desktop → Settings → Resources → WSL Integration for this distro, or run those commands on a host where `docker` is available. Mark Task 6 as blocked until Docker is available.
- `.gitignore` excludes the `docs/` directory (use `git add -f` for any new `docs/` file) and `.env.example` (local-only — never staged/committed).
- `scoring_weights.yaml` weights must sum to 1.0 — not touched by this plan, but re-run scoring tests after any YAML edit. Not needed here.
- Formal-run rule: `alibaba_allow_mock_suppliers` default must be `False`; compose env must hard-set `ALIBABA_ALLOW_MOCK_SUPPLIERS=false`. The `_mock_suppliers` code and `smoke-run --allow-mock` flag are retained.

**Reference spec:** `docs/superpowers/specs/2026-07-07-docker-packaging-design.md` (committed `b5f54b4`).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `config/settings.py` | Holds `alibaba_allow_mock_suppliers` default. | Modify line 121. |
| `tests/test_settings_mock_default.py` | Asserts the mock default is `False` hermetically. | Create. |
| `docker-entrypoint.sh` | Runs idempotent `init-db`, then `exec`s the real command. | Create. |
| `Dockerfile` | Single-stage image: deps + 2 browsers + app + entrypoint + EXPOSE. | Rewrite. |
| `docker-compose.yml` | One overridable service: server default, ports, mock-disabled env. | Rewrite. |
| `.dockerignore` | Excludes `.venv/`, `.playwright-mcp/`, `*.png`, `dashboard.html` from build context. | Modify. |
| `.env.example` | Local env template (gitignored, not committed). | Create. |
| `README.md` | Docker usage + env-var reference (tracked, since `.env.example` is not). | Modify. |

---

### Task 1: Disable mock suppliers by default (TDD)

Plain `python main.py run` calls `run_pipeline` directly and never overrides `alibaba_allow_mock_suppliers` (only `smoke-run`/`AgentRuntime` do). So the *default* in `config/settings.py` decides whether mock fires on a blocked 1688 path. Flip it to `False`.

**Files:**
- Create: `tests/test_settings_mock_default.py`
- Modify: `config/settings.py:121`
- Test: `tests/test_settings_mock_default.py`

**Interfaces:**
- Consumes: `config.settings.Settings` (existing).
- Produces: `settings.alibaba_allow_mock_suppliers` defaults to `False`. Consumed by `matchers/__init__.py:220` (the mock-skip gate) and reported by `agent/config_status.py:54`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_mock_default.py`:

```python
from config.settings import Settings


def test_mock_suppliers_disabled_by_default(monkeypatch):
    """Formal runs must not emit mock suppliers unless explicitly opted in.

    Plain `main.py run` does not override this flag (only smoke-run/AgentRuntime
    do), so the class default governs whether a blocked 1688 path falls back to
    mock. It must be False.
    """
    monkeypatch.delenv("ALIBABA_ALLOW_MOCK_SUPPLIERS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.alibaba_allow_mock_suppliers is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings_mock_default.py -v`
Expected: FAIL with `assert True is False` (current default is `True`).

- [ ] **Step 3: Flip the default**

Edit `config/settings.py` line 121. Replace:

```python
    alibaba_allow_mock_suppliers: bool = True
```

with:

```python
    alibaba_allow_mock_suppliers: bool = False  # formal runs: mock off by default; smoke-run --allow-mock opts in
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings_mock_default.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Confirm no regression in mock-related tests**

The three tests that touch mock all monkeypatch the flag explicitly, so the default flip must not change their behavior. Verify:

Run: `pytest tests/test_smoke_run.py tests/test_alibaba_result_cache.py tests/test_matchers_manual_queue.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full unit suite to be safe**

Run: `pytest tests/ -q`
Expected: no new failures vs. baseline (the suite runs offline with mock DTOs).

- [ ] **Step 7: Commit**

```bash
git add config/settings.py tests/test_settings_mock_default.py
git commit -m "Disable mock suppliers by default for formal runs

Flip alibaba_allow_mock_suppliers default True→False so plain
`main.py run` no longer falls back to mock on a blocked 1688 path.
smoke-run --allow-mock and AgentRuntime still opt in explicitly."
```

---

### Task 2: Create `docker-entrypoint.sh`

The server (`agent/server.py`) does not call `init_db()` on startup, so a fresh `data/` volume would hit "no such table" on the first DB-touching API. This shim runs idempotent `init-db` (which calls `Base.metadata.create_all`) before every container start.

**Files:**
- Create: `docker-entrypoint.sh`

**Interfaces:**
- Consumes: `python main.py init-db` (existing CLI command) and `python main.py <subcommand>` (existing).
- Produces: an executable entrypoint that the Dockerfile `ENTRYPOINT` will reference in Task 3, and that compose `command` args append to.

- [ ] **Step 1: Write the entrypoint script**

Create `docker-entrypoint.sh`:

```sh
#!/bin/sh
set -e
# Idempotent: create_all is a no-op when tables already exist.
python main.py init-db || echo "[entrypoint] init-db failed, continuing" >&2
exec python main.py "$@"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x docker-entrypoint.sh`
Expected: no output; `ls -l docker-entrypoint.sh` shows `rwxr-xr-x`.

- [ ] **Step 3: Syntax check (no Docker needed)**

Run: `sh -n docker-entrypoint.sh`
Expected: no output, exit 0 (syntax OK).

- [ ] **Step 4: Commit**

```bash
git add docker-entrypoint.sh
git commit -m "Add docker-entrypoint.sh to bootstrap DB before container start"
```

---

### Task 3: Rewrite the `Dockerfile`

The existing `Dockerfile` (2026-05-14) predates the agent WebUI and never runs `scrapling install` (so the default Amazon scraper has no patchright browser). Rewrite it single-stage per the spec.

**Files:**
- Modify (rewrite): `Dockerfile`

**Interfaces:**
- Consumes: `docker-entrypoint.sh` (Task 2), `requirements.txt`, the app source.
- Produces: an image `amazon-selector:dev` with `ENTRYPOINT ["./docker-entrypoint.sh"]` and `CMD ["agent-web","--host","0.0.0.0","--port","8765"]`, exposing 8765.

- [ ] **Step 1: Rewrite the Dockerfile**

Replace the entire contents of `Dockerfile` with:

```dockerfile
FROM python:3.12-slim

# Chromium system libraries (Playwright-managed; replaces hand-maintained apt list).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl fonts-liberation \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (layered for cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers: playwright chromium (1688 Playwright matcher) + scrapling patchright
# (default Amazon scraper — the step the old Dockerfile was missing).
RUN python -m playwright install chromium \
    && scrapling install

# Application code (respects .dockerignore).
COPY . .

# Runtime data dirs (mounted volume overlays these).
RUN mkdir -p /app/data/cache /app/data/exports /app/data/images

# Entrypoint: ensure DB tables exist, then run the requested command.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8765
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["agent-web", "--host", "0.0.0.0", "--port", "8765"]
```

- [ ] **Step 2: Verify against the spec checklist**

Confirm the rewritten `Dockerfile` contains each required element (read the file back):

- `FROM python:3.12-slim`
- `python -m playwright install-deps chromium` (system libs)
- `python -m playwright install chromium` (playwright browser)
- `scrapling install` (patchright browser)
- `COPY docker-entrypoint.sh` + `chmod +x`
- `EXPOSE 8765`
- `ENTRYPOINT ["./docker-entrypoint.sh"]`
- `CMD ["agent-web", "--host", "0.0.0.0", "--port", "8765"]`

If any are missing, fix the Dockerfile before committing.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "Rewrite Dockerfile: add scrapling/patchright browser, agent-web CMD

Single-stage on python:3.12-slim. Installs playwright chromium (1688
Playwright matcher) AND scrapling patchright (default Amazon scraper,
which the old Dockerfile was missing). Uses playwright install-deps for
system libs. Exposes 8765 and defaults to agent-web server."
```

The actual `docker build` is deferred to Task 6 (Docker not available in this WSL distro).

---

### Task 4: Rewrite `docker-compose.yml`

One overridable service: `up` runs the server; `docker compose run --rm amazon-selector <cli args>` replaces `command` and runs the CLI. Mock disabled via env.

**Files:**
- Modify (rewrite): `docker-compose.yml`

**Interfaces:**
- Consumes: the image built in Task 3; `docker-entrypoint.sh` (ENTRYPOINT). CLI subcommands from `main.py`.
- Produces: a compose service exposing `127.0.0.1:8765`, mounting `./data:/app/data`, reading `.env`, and hard-setting `ALIBABA_ALLOW_MOCK_SUPPLIERS=false`.

- [ ] **Step 1: Rewrite docker-compose.yml**

Replace the entire contents of `docker-compose.yml` with:

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

- [ ] **Step 2: Validate the compose file**

If Docker is available: `docker compose config -q` (expected: exit 0, no output).

If Docker is NOT available (current WSL state): open `docker-compose.yml` and confirm:
- `services.amazon-selector` exists.
- `environment.ALIBABA_ALLOW_MOCK_SUPPLIERS` is `"false"`.
- `ports` is `127.0.0.1:8765:8765`.
- `volumes` includes `./data:/app/data`.
- `command` is `["agent-web", "--host", "0.0.0.0", "--port", "8765"]`.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "Rewrite docker-compose: server default command, port 8765, mock disabled

Single overridable service: `up` runs agent-web on 127.0.0.1:8765;
`run --rm amazon-selector <cmd>` replaces command for CLI jobs.
Hard-sets ALIBABA_ALLOW_MOCK_SUPPLIERS=false for formal runs."
```

---

### Task 5: `.dockerignore` + `.env.example` + README Docker section

Three small supporting artifacts. `.dockerignore` shrinks the build context (the local `.venv` is hundreds of MB and must not be COPY'd into the image). `.env.example` is a local template (gitignored). README carries the canonical Docker + env-var reference (tracked, since `.env.example` is not).

**Files:**
- Modify: `.dockerignore`
- Create: `.env.example` (local-only, gitignored — will NOT be staged)
- Modify: `README.md`

**Interfaces:**
- Consumes: the list of env vars in `config/settings.py`.
- Produces: a leaner build context (`.dockerignore`), a local env template (`.env.example`), and tracked deploy docs (README).

- [ ] **Step 1: Update `.dockerignore`**

Read `.dockerignore`. Append these four lines at the end:

```
.venv/
.playwright-mcp/
*.png
dashboard.html
```

(Use the Edit tool: `old_string` = the current last line `.dockerignore`, `new_string` = `.dockerignore\n.venv/\n.playwright-mcp/\n*.png\ndashboard.html`.)

- [ ] **Step 2: Create `.env.example` (local-only)**

Create `.env.example`:

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

Note: `.gitignore` line 29 excludes `.env.example`, so `git status` will not show it and `git add` will not stage it. That is expected — it is a local file. Do not force-add it.

- [ ] **Step 3: Add a Docker section to `README.md`**

Insert a new `## Docker` section between the `## Agent WebUI` section (ends at line 47) and the `## 一次性登录（首次使用必做）` section. Use the Edit tool with:

- `old_string` = `## 一次性登录（首次使用必做）`
- `new_string` = the Docker section below, followed by a blank line and `## 一次性登录（首次使用必做）`

Docker section content:

```markdown
## Docker

本项目支持 Docker 部署，**正式跑默认禁用 mock 供应商**（`alibaba_allow_mock_suppliers` 默认 False，compose 环境变量再次硬设 `false`）。

```bash
# 构建镜像（python:3.12-slim + playwright chromium + scrapling patchright）
docker compose build

# 启动 Agent WebUI（长驻服务，端口映射到本机 127.0.0.1:8765）
docker compose up
# 打开 http://127.0.0.1:8765

# 一次性 CLI 任务（command 会被替换；entrypoint 仍会先跑 init-db）
docker compose run --rm amazon-selector run --category "Home & Kitchen" --limit 50
docker compose run --rm amazon-selector init-db
docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --limit 1

# 容器内跑测试
docker compose run --rm amazon-selector pytest tests/ -q
```

数据持久化：`./data:/app/data` 卷挂载，SQLite 数据库、缓存、cookies、导出文件都落在这里。首次启动时 entrypoint 会自动跑 `init-db` 建表。

环境变量：参考 `.env.example`（本地文件，未入库）填好 `.env`，至少需要 `PPIO_API_KEY`（视觉识别）。Amazon/1688 爬虫需要 cookies——在宿主机跑 `setup_amazon_login.py` / `setup_1688_login.py` 生成后放入 `data/`，容器通过卷挂载读取。关键变量：`PPIO_API_KEY`（视觉识别，必需）、`KEEPA_API_KEY`/`RAINFOREST_API_KEY`（Amazon API 抓取，可选，否则走 scrapling）、`MJJL_API_KEY`（卖家精灵市场分析，可选）、`ALIBABA_ALLOW_MOCK_SUPPLIERS`（正式跑保持 `false`）。
```

- [ ] **Step 4: Verify `.dockerignore` and README**

Run: `tail -n 6 .dockerignore`
Expected: the last lines include `.venv/`, `.playwright-mcp/`, `*.png`, `dashboard.html`.

Run: `grep -n "## Docker" README.md`
Expected: one match, e.g. `48:## Docker`.

- [ ] **Step 5: Commit (`.env.example` is gitignored — only `.dockerignore` + `README.md` are staged)**

```bash
git add .dockerignore README.md
git commit -m "Lean .dockerignore, README Docker section, local .env.example

.dockerignore now excludes .venv/ (.playwright-mcp/, *.png,
dashboard.html) so COPY . . doesn't ship the host venv into the image.
README documents docker compose up/run + env-var reference (.env.example
is gitignored alongside .env, so the canonical reference lives here)."
```

Confirm `git status` shows `.env.example` as untracked/ignored (not staged). It is intentional.

---

### Task 6: Build & verify (requires Docker — BLOCKED in current WSL distro)

**Precondition:** `docker` and `docker compose` must be available. In the current WSL2 distro `docker` is not found — enable Docker Desktop → Settings → Resources → WSL Integration for this distro, or run these steps on a host with Docker. Do NOT mark this task complete until the verification commands pass.

**Files:**
- No file changes. This task only builds and runs the image produced by Tasks 2–5 and verifies the behavior required by the spec.

- [ ] **Step 1: Build the image**

Run: `docker compose build`
Expected: build completes; final line names the image `amazon-selector:dev`. Exit 0. Watch for `scrapling install` and `playwright install chromium` both succeeding (no error about a missing browser).

- [ ] **Step 2: CLI entrypoint works**

Run: `docker compose run --rm amazon-selector --help`
Expected: prints the click CLI help (`Usage: main.py [OPTIONS] COMMAND [ARGS]...` and a `Commands:` list including `init-db`, `run`, `smoke-run`, `agent-web`). Exit 0.

- [ ] **Step 3: Unit tests pass inside the container**

Run: `docker compose run --rm amazon-selector pytest tests/ -q`
Expected: all tests pass (offline; no API keys needed). Exit 0.

- [ ] **Step 4: Mock guard**

Run: `docker compose run --rm amazon-selector python -c "from config.settings import settings; assert settings.alibaba_allow_mock_suppliers is False; print('mock disabled')"`
Expected: prints `mock disabled`. Exit 0. (Confirms compose env override takes effect.)

- [ ] **Step 5: Server starts and serves the WebUI**

Run: `docker compose up -d`
Then: `curl -sI http://127.0.0.1:8765`
Expected: an HTTP response (status `200` or `301`/`302` is fine — the server serves the static WebUI HTML at `/`). 
Then: `docker compose down`

Also confirm the entrypoint created the DB on a fresh volume:
Run: `ls -la data/amazon_selector.db`
Expected: the file exists (created by the entrypoint's `init-db` on first start).

- [ ] **Step 6 (optional, slow): Chromium launches inside the container**

Run: `docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --limit 1 --skip-preflight`
Expected: the command runs and attempts to launch patchright/playwright Chromium. It may fail on 1688 captcha or missing keys — that is an external/environment issue, NOT a Docker defect. What matters: no error of the form "Executable doesn't exist" or "browser not found" (that would mean `scrapling install`/`playwright install` failed at build time). If you see a browser-missing error, revisit Task 3's browser-install steps.

- [ ] **Step 7: No commit needed**

Task 6 produces no file changes. If all steps pass, the Docker packaging is complete and verified.

---

## Self-Review (run before handoff)

**Spec coverage:**
- Dockerfile (single stage, scrapling install, EXPOSE, entrypoint, server CMD) → Task 3. ✓
- docker-entrypoint.sh (init-db then exec) → Task 2. ✓
- docker-compose.yml (server default, ports 127.0.0.1:8765, mock=false env, restart) → Task 4. ✓
- .dockerignore (.venv/, .playwright-mcp/, *.png, dashboard.html) → Task 5 Step 1. ✓
- .env.example (local-only) → Task 5 Step 2. ✓
- Mock disablement (settings default flip + compose env) → Task 1 + Task 4. ✓
- README Docker section + env-var reference → Task 5 Step 3. ✓
- Verification plan (build → --help → pytest → up+curl → mock guard → smoke-run) → Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step contains the actual content; commands have expected output. ✓

**Type/name consistency:** `alibaba_allow_mock_suppliers` (snake_case field) ↔ `ALIBABA_ALLOW_MOCK_SUPPLIERS` (env var, pydantic-settings case-insensitive) — matches existing usage in `agent/runner.py`. `docker-entrypoint.sh` referenced identically in Task 2 (create), Task 3 (COPY/ENTRYPOINT), Task 4 (consumed via image). ✓

No issues found.
