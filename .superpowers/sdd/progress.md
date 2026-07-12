# SDD Progress Ledger — Docker Packaging

Plan: docs/superpowers/plans/2026-07-07-docker-packaging.md
Branch: dev0.1 (kept as-is per user choice)
Base: 2b32bb7

## Tasks

- Task 1: complete (commits 2b32bb7..c67895d, review clean) — Disable mock suppliers by default (TDD)
- Task 2: complete (commits c67895d..5530d02, review clean after mode-bit fix) — Create docker-entrypoint.sh
- Task 3: complete (commits 5530d02..9bc113d, review clean) — Rewrite Dockerfile
- Task 4: complete (commits 9bc113d..94cec07, review clean) — Rewrite docker-compose.yml
- Task 5: complete (commits 94cec07..6db2cc4, review clean) — .dockerignore + .env.example + README Docker section
- Task 6: USER HANDOFF (requires Docker — not in this WSL distro; user runs when Docker Desktop WSL integration enabled)

## Final whole-branch review

- Scope: 2b32bb7..6db2cc4 (5 task commits, 7 files, +73/-30). Reviewer: fable. Verdict: **Ready to merge: Yes.** No Critical, no Important.

## Test state (verified)

- Committed branch (isolated worktree at 6db2cc4, no WIP): 187 passed, 1 failed, 5 skipped. The 1 failure is `test_maijiajingling.py::test_analyze_market_populates_sales_competition_and_keyword_metrics` — pre-existing SOCKS-proxy/socksio env error, unrelated to Docker (my commits don't touch maijiajingling or proxy config).
- Working tree (with user WIP): 313 passed, 5 failed, 5 skipped. The 5 failures are the user's in-progress maijiajingling refactor (uncommitted WIP), not the Docker branch.
- My Docker work introduces zero test failures; `tests/test_settings_mock_default.py` passes.

## Finishing

- User chose: keep dev0.1 as-is. No merge/push/cleanup. Commits stay on dev0.1; user WIP untouched.

## Minor findings (all optional, none blocking — deferred per final review)

1. `docker-compose.yml` `env_file: .env` required-by-default in Compose v2.24+ → fresh clone w/o `.env` fails before build. Pre-existing, spec-mandated. Optional fix: `env_file: - path: .env; required: false`.
2. `Dockerfile` redundant `COPY docker-entrypoint.sh` after `COPY . .` (belt-and-suspenders; harmless).
3. `Dockerfile` build-time `mkdir /app/data/{cache,exports,images}` masked by volume (harmless — settings properties self-create).
4. `Dockerfile` `curl` installed but unused (debug convenience; few MB).

## Task 6 handoff (user-run, requires Docker)

1. `docker compose build` — confirm `playwright install chromium` + `scrapling install` succeed.
2. `docker compose run --rm amazon-selector --help`
3. `docker compose run --rm amazon-selector pytest tests/ -q`
4. `docker compose run --rm amazon-selector python -c "from config.settings import settings; assert settings.alibaba_allow_mock_suppliers is False; print('mock disabled')"`
5. `docker compose up -d` + `curl -sI http://127.0.0.1:8765`; `ls -la data/amazon_selector.db` (entrypoint bootstrapped DB).
6. (optional) `docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --limit 1 --skip-preflight` — confirms patchright/playwright Chromium launches in-container (the one genuine runtime risk: whether `scrapling install` places patchright chromium where `StealthySession` expects).

## Notes

- Task 1: commit split to exclude settings.py WIP; final c67895d (flip + test only).
- Task 2: implementer's first commit lost exec bit (100644); controller amended to 5530d02 (100755).
- Branch dev0.1 carries user's extensive uncommitted WIP; only 7 Docker-related files committed by this work.

---

# SDD Progress Ledger — Sourcing Quality Vertical Slice

Plan: docs/superpowers/plans/2026-07-10-sourcing-quality-vertical-slice.md
Branch: dev0.1 (in-place execution explicitly requested by user)
Base: 37372f9

## Tasks

- Task 1: complete (commits 658faed..7542863, review clean; minor: explicit naive `now` can still raise TypeError) — Canonical evidence and decision schemas
- Task 2: complete (commits 7542863..de49cdc, review approved; focused 8 passed; full suite environment-blocked by D/jbd2 I/O; minor: mixed-sign completed audit reason precision) — Additive SQLite migration foundation
- Task 3: complete (commits de49cdc..a29de7e, review clean; full 432 passed, 5 skipped) — Fix negative visual semantics and remove rejected fallback admission
- Task 4: complete (commits a29de7e..254299e, review clean; full 483 passed, 5 skipped) — Gate profit and scoring on critical evidence
- Task 5: complete (commits 254299e..be9853c, review approved; full 499 passed, 5 skipped; minor import cleanup deferred) — Enrich Amazon detail, buy box, and market evidence
- Task 6: complete (commits be9853c..9b533a8, review approved; full 518 passed, 5 skipped; minor short-brand token boundary deferred) — Structured Amazon product understanding
- Task 7: complete (commits 9b533a8..503f434, review approved; full 528 passed, 5 skipped; report wording minor deferred) — Twelve-type de-branded query planning
- Task 8: complete (commits 503f434..b2252af, review clean; full 556 passed, 5 skipped) — Safe 1688 offer detail extraction and provenance
- Task 9: complete (commits b2252af..4df7f57, review approved; full 591 passed, 5 skipped; focused count wording minor) — Structured MatchEvidence and minimum evidence threshold
- Task 10: complete (commits 4df7f57..c766584, review clean; full 605 passed, 5 skipped) — Schema-validated dual-image verification
- Task 11: complete (commits c766584..edc9017, final review approved; focused 81 passed; full 669 passed, 5 skipped) — Bounded sourcing slice and evidence exports
- Task 12: complete (commits 8fd369c..d739514, review approved; focused 9 passed; empty predictions preserve null metrics) — Benchmark evaluator with honest denominators
- Task 13: complete (commits 64d8308..a701379, review approved; focused 46 passed; final full 679 passed, 5 skipped; copied DB integrity/FK clean; real no-mock E2E externally blocked before crawl by invalid market key) — Compatibility, full verification, and real no-mock E2E

## Final whole-branch review

- In progress for feature scope `658faed..a701379` (Tasks 1–13; excludes the pre-existing/user commit at the base).
