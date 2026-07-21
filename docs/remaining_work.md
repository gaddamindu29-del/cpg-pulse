# CPG Pulse — Handoff / Remaining Work

Written 2026-07-21, at the end of the session that built Phases 1-7. This
session hit its token limit — Phases 8-10 were **not started**. This document
is the continuation brief for whoever (human or a new Claude Code session)
picks this up next.

## 1. Exact Current Status

Phases 1-7 are **complete and live-validated** (not just written — actually
executed against a real Postgres warehouse, a real FastAPI server, and a real
browser session; see `docs/checklist.md` for the full evidence trail,
including 6+ real bugs found and fixed during validation).

| Phase | Status |
|---|---|
| 1. Architecture & planning | ✅ Done — `docs/architecture.md` |
| 2. Synthetic data generator | ✅ Done, tested (38 unit tests) |
| 3. Local dev environment (Docker Compose) | ✅ Done, config-validated (daemon never available in this sandbox, so `docker compose up` itself was never run) |
| 4. Ingestion + PySpark standardization | ✅ Ingestion done & tested live. PySpark jobs written but **never executed** (see §5) |
| 5. Warehouse + dbt (staging/snapshots/marts) | ✅ Done, live-validated (89 dbt tests passing) |
| 6. Analytics logic (dbt intermediate + analytics marts) | ✅ Done, live-validated |
| 7. FastAPI + Streamlit dashboard | ✅ Done, live-validated (28 API tests passing, all 6 dashboard pages screenshotted) |
| 8. Testing (integration/DQ/idempotency/late-arriving/schema-change) | ❌ **Not started** |
| 9. CI/CD (GitHub Actions) | ❌ **Not started** |
| 10. Documentation (README, data dictionary, mappings, metrics, runbook) | ❌ **Not started** |

No commits existed before this handoff. This session ran `git init` at the
very start (empty repo) and this handoff commits everything built so far in
one commit — see the end of this document / the actual git log for the
message used.

## 2. Remaining Work — Priority Order

### Phase 8 — Testing (do this first: it validates everything below depends on)
1. **Idempotency test** — re-run ingestion + dbt against the same data, assert no duplicate rows / stable row counts. The pattern is already proven manually (see §3 commands); just needs to be a real pytest in `tests/integration/`.
2. **Late-arriving-data test** — generator already injects late arrivals (`pos_late_arrival_rate` in `scripts/data_gen/config.py`); write a test that ingests, then ingests again after "discovering" a late file, and asserts the affected partition gets reprocessed.
3. **Schema-change test** — the reserved_qty→reserved_units rename is real, already-generated test data; write a test asserting `ingestion/common/schema_check.py` detects it as `TYPE_CHANGED`/breaking (this exact scenario was manually verified working during Phase 4 — see `docs/checklist.md`).
4. **Duplicate-record test** — generator injects exact duplicates (`pos_duplicate_rate`); assert dbt staging's `row_number()` dedup collapses them (see `dbt/models/staging/stg_retail_pos_sales.sql`).
5. **Invalid-product-mapping test** — assert rows with unresolvable `retailer_product_id` get quarantined (Spark path) or dropped-and-logged (fallback loader path — see `scripts/load_to_warehouse.py::_fallback_standardize`).
6. **dbt tests** — already done (89 passing), nothing more needed here structurally, but re-run them as part of whatever CI you build in Phase 9.
7. **Data-quality tests** — `tests/data_quality/` is empty; add tests that run `spark/quality/dq_engine.py` suites against known-good and known-bad fixtures and assert pass/fail counts.
8. Fill out `tests/unit/` and `tests/integration/` for the ingestion engine (`ingestion/common/base_ingest.py`) — it was validated manually with a monkeypatched DB (see §3) but has no actual pytest file yet. That monkeypatch pattern is reusable; lift it into `tests/integration/test_ingestion.py`.

### Phase 9 — CI/CD
1. GitHub Actions workflow (`.github/workflows/ci.yml`, does not exist yet):
   - Install deps (`pip install -r requirements.txt`)
   - Lint (`ruff check`)
   - Run `tests/unit/` and `api/tests/` — **these need a Postgres service container** in the workflow (API tests hit a real DB by design; see §5's "not mockable" note)
   - `dbt deps && dbt compile` (and ideally `dbt run && dbt test` against the CI Postgres service, seeded via `scripts/load_to_warehouse.py --generated-dir data/sample`)
   - Build the `api/Dockerfile` and `dashboard/Dockerfile` images (build-only is fine; no push needed)
   - Secret-scanning / prevent-committed-secrets step
2. This is the natural place to also wire up `dbt/profiles.yml` generation from GitHub Actions secrets/env — don't commit a real one (see §6).

### Phase 10 — Documentation
1. **README.md** (repo root, does not exist yet) — this is the single most
   important remaining deliverable for portfolio purposes. Must cover:
   business problem, architecture diagram (reuse the Mermaid diagram from
   `docs/architecture.md`), tech stack, setup/run instructions (`make setup`,
   `make up`, `make generate-data`, `make dbt-run`, `make api`, `make
   dashboard` — all already real and working), testing instructions,
   screenshots section (**use the real dashboard screenshots** — see §3 for
   how to regenerate them; do not fabricate what they show), known
   limitations (§5 below is the source of truth), future enhancements,
   interview talking points.
2. `docs/data_dictionary.md` — column-level docs for all 9 sources +
   warehouse tables. Source field lists already exist in
   `scripts/data_gen/config.py` / the original spec; warehouse schema is in
   `warehouse/postgres/warehouse_schema.sql` (verified-accurate against a
   live DB — use it as the source of truth, not the Snowflake file, which was
   never executed).
3. `docs/source_to_target_mapping.md` — trace each of the 9 sources through
   raw → standardized → curated → staging → marts. The mapping is
   implicit in the code today (`ingestion/*/ingest.py` → `spark/jobs/*.py` →
   `dbt/models/staging/*.sql` → `dbt/models/marts/**/*.sql`); this doc should
   make it explicit and readable without reading code.
4. `docs/metrics.md` — formula documentation for every metric in the
   "Required Business Metrics" list from the original spec. Most formulas
   already exist as SQL in `dbt/models/marts/analytics/*.sql` with inline
   comments explaining the business logic — this doc should extract and
   formalize them, **including the promotion-lift sample-size caveat** found
   during Phase 6 validation (see `docs/checklist.md` Phase 6 section) and
   the explicit "this is an estimate, not causal inference" framing already
   in `mart_promotion_effectiveness.sql`.
5. `docs/runbook.md` — operational runbook. Should fold in every "Known
   quirks" comment already scattered through the codebase (grep for "known
   quirk", "caught during", "bit a real run" — there are several, each
   documenting a real bug found during this session's live validation).
6. `docs/interview_prep.md` — resume bullets + interview Q&A, per the
   original spec's Phase 10 ask. Draw on the real validation work in
   `docs/checklist.md` (finding and fixing 6+ real bugs via live testing is
   itself a strong interview story — don't undersell it).

## 3. Commands Already Used to Run and Validate the Project

These all worked, for real, in this session. Docker was never available
(daemon not running in this sandbox), so validation used an **isolated,
throwaway local Postgres 18 cluster** (via `initdb`/`pg_ctl`, NOT the user's
pre-existing local Postgres, NOT the Docker Compose one) and a disposable
`.venv-test/` virtualenv in the repo root. Both were deliberately kept
separate from the real deliverable. The throwaway Postgres cluster lived in
the session's scratchpad temp directory and will **not** persist into a new
session — recreate equivalent state via `make up` (the real, intended path)
instead of trying to reconstruct the throwaway one.

```bash
# --- Generator ---
python scripts/generate_synthetic_data.py                      # full dataset (~4 min, ~1.6GB, gitignored)
python scripts/generate_synthetic_data.py --start-date 2025-01-01 --end-date 2025-02-28 \
  --num-products 12 --stores-per-retailer "RTL-WMT=3,RTL-TGT=2,RTL-KRG=2,RTL-AMZ=1" \
  --output-dir data/sample                                      # small committed sample
pytest tests/unit/test_generator.py -v                          # 38 tests, all passing

# --- Local warehouse setup (substitute your own Postgres; Docker Compose is the real path) ---
# initdb / pg_ctl / createdb were used in this session only because Docker's
# daemon wasn't running -- in a normal environment just `make up` instead.
psql -f warehouse/postgres/metadata_schema.sql                  # validated clean against real Postgres 18
python scripts/load_to_warehouse.py --generated-dir data/sample # loads landing.* tables

# --- dbt ---
cd dbt
export DBT_PROFILES_DIR=$(pwd)   # profiles.yml.example must be copied to profiles.yml locally (gitignored)
dbt deps
dbt seed
dbt snapshot
dbt run
dbt test                                                          # 89 tests, all passing
dbt docs generate                                                 # confirmed clean, 2 exposures recognized

# --- API ---
uvicorn api.main:app --host 127.0.0.1 --port 8000                # or: make api
pytest api/tests/test_api.py -v                                   # 28 tests, all passing (hits a REAL db, not mocked)
curl http://localhost:8000/health

# --- Dashboard ---
streamlit run dashboard/app.py                                    # or: make dashboard
# DASHBOARD_API_BASE_URL env var must point at the running API
# Verified visually via Playwright (installed ad hoc: `python -m playwright install chromium`)
# by opening the app, clicking through all 6 pages, and screenshotting each --
# this is how the upc bigint/text bug (see §5) was actually caught.
```

## 4. Current Test Counts (all verified passing, this session)

| Suite | Count | Command |
|---|---|---|
| Generator unit tests | 38 | `pytest tests/unit/test_generator.py -v` |
| dbt schema/data tests | 89 | `cd dbt && dbt test` |
| API integration tests | 28 | `pytest api/tests/test_api.py -v` |
| **Total** | **155** | |

None of these are in CI yet (Phase 9 not started) — they were only run
manually in this session's throwaway environment.

## 5. Known Limitations and Untested Components

Be honest about these in the README (Phase 10) — do not claim more than what
was actually verified.

- **PySpark jobs were never executed.** `spark/jobs/standardize_pos_sales.py`
  and `spark/jobs/standardize_inventory.py` are code-reviewed and use
  standard, well-established PySpark DataFrame APIs, but this Windows +
  Python 3.12 sandbox hit worker-crash issues with Spark 3.5.1 regardless of
  JDK version (tried both 17 and 23) — a known class of Windows-native
  PySpark friction, not a code defect. **Never actually validated.** The
  intended runtime is the Docker `airflow` container (Linux, Python 3.11,
  pinned Java) from Phase 3 — that's the first thing to try in an environment
  where Docker actually runs.
- **`spark/quality/dq_engine.py` and `spark/jobs/run_quality_checks.py`**
  were unit-tested in isolation via a small standalone script during Phase 4,
  but never run end-to-end as part of the real pipeline (follows from the
  PySpark limitation above). `landing.dq_results` / `marts.mart_data_quality_summary`
  are consequently **empty** in every live validation this session did — the
  dashboard's Data Quality page was confirmed to *handle that gracefully*
  (empty-state message, no crash), but was never seen with real DQ data in it.
- **Spark standardization jobs for shipments, promotions, and ecommerce_orders
  were never built** (only `retail_pos_sales` and `retail_inventory` got full
  Spark jobs — see `docs/checklist.md` Phase 4 notes for the reasoning: time
  was prioritized toward breadth across phases over exhaustive per-source
  duplication). The pattern to follow is fully established in
  `spark/jobs/standardize_pos_sales.py` + `spark/transformations/common.py`.
- **`docker compose up` was never run.** Only `docker compose config`
  (schema/interpolation validation, no daemon needed) was verified. The
  Postgres DDL, dbt project, API, and dashboard were all validated against a
  hand-rolled equivalent (isolated local Postgres + bare `uvicorn`/`streamlit`
  processes), not the actual container stack. Airflow was never started;
  no DAGs were ever actually scheduled/run (they don't exist yet regardless
  — Airflow DAG files were never written, despite being listed in the
  original spec's 12-DAG requirement and referenced by name in code
  docstrings, e.g. `dag_id="retail_pos_sales_ingestion"`).
- **`data/lake` (the local-filesystem storage backend) only has data from
  ad hoc ingestion tests**, not a full pipeline run. It's gitignored and
  won't exist in a fresh clone.
- **The local-dev fallback loader (`scripts/load_to_warehouse.py`) is
  deliberately simpler than the real Spark standardization path** — no
  quarantine-with-reason, no store validation. It exists purely so the dbt
  project could be exercised without working PySpark in this sandbox. A
  fresh session with working Docker/Spark should prefer the real pipeline
  (ingestion → Spark → curated → `load_to_warehouse.py`'s "real pipeline
  path" branch) and treat the fallback as a documented convenience, not the
  source of truth.
- **No Snowflake account was ever available.** `warehouse/snowflake/warehouse_schema.sql`
  is a careful manual translation of the live-verified Postgres DDL, but was
  never executed against real Snowflake.
- **Airflow DAG files do not exist yet** (`airflow/dags/` is empty except for
  what Docker Compose expects to mount there). This is arguably a gap in
  Phase 4/architecture rather than Phase 8-10, flagging it here since it's
  easy to miss.

## 6. Architectural Decisions That Must Not Be Changed

These were deliberate, and in several cases fixed a real bug — reverting them
will reintroduce that bug.

1. **`dbt/macros/generate_schema_name.sql` overrides dbt's default schema
   naming.** Without it, dbt produces `marts_marts`/`marts_staging` instead
   of clean `marts`/`staging` schema names (dbt's default behavior is to
   concatenate target schema + custom schema). Do not delete this macro.
2. **The SCD2 snapshots (`dbt/snapshots/dim_product_snapshot.sql`,
   `dim_store_snapshot.sql`) must select from the staging models
   (`ref('stg_product_master')`, `ref('stg_store_master')`), never straight
   from `source('landing', ...)`.** Reading from raw source directly was a
   real bug: it let `upc` come through as `bigint` (breaking the API's
   Pydantic model, which correctly requires `str` — UPCs are identifiers,
   never numbers) and let dates come through as full timestamps instead of
   `date`. Any new snapshot must follow the same pattern.
3. **`scripts/load_to_warehouse.py`'s `_replace_table()` helper does an
   explicit `DROP TABLE ... CASCADE` before reload, not a plain
   `df.to_sql(if_exists='replace')`.** Plain replace fails once dbt has
   created views/tables depending on the landing tables
   (`DependentObjectsStillExist`). Keep the CASCADE-drop pattern for any new
   landing-table load.
4. **`scripts/load_to_warehouse.py`'s `_coerce_date_columns()` explicitly
   parses any `*_date` column to datetime before loading**, even when every
   value in a given batch happens to be null. Removing this reintroduces a
   real bug: an all-null column gets inferred as `float64` by pandas, which
   Postgres can't cast to `date`.
5. **Raw lake layer is a byte-exact copy of source files — no lineage
   columns, no row mutation, no schema-gating.** Ingestion (`ingestion/common/base_ingest.py`)
   always lands the file even when it detects a breaking schema change; it
   only *logs* the change (`schema_change_log`). This was a deliberate
   correction made mid-session (see `docs/checklist.md` Phase 4) after an
   earlier draft wrongly gated raw landing on schema validity. Lineage
   columns are added at **standardization** time, not ingestion time.
6. **The `reserved_qty` → `reserved_units` column alias must be handled by
   name-coalescing** (`spark/transformations/common.py::rename_columns`,
   mirrored in `scripts/load_to_warehouse.py::_fallback_standardize`), not by
   picking one canonical name and dropping the other. A single raw batch can
   legitimately contain both column names at once (a late-arriving
   pre-schema-change file landing in the same `extract_date` partition as an
   on-time post-change file) — this was observed for real during Phase 4
   testing, not a hypothetical.
7. **`GeneratorConfig.rng()` (`scripts/data_gen/config.py`) uses `hashlib`,
   never Python's built-in `hash()`,** to derive per-stream random seeds.
   `hash()` on strings is salted per-process (`PYTHONHASHSEED`) and silently
   broke cross-run reproducibility despite a fixed `--seed` — a real bug
   caught and regression-tested (`test_rng_stream_seed_independent_of_python_hash_randomization`
   in `tests/unit/test_generator.py`).
8. **Incremental fact models use `incremental_strategy='delete+insert'`**,
   confirmed working against dbt-postgres 1.8.2 (produced `INSERT 0 0` on a
   no-op re-run, proving idempotency). Don't switch to `merge` without
   re-verifying dbt-postgres support for it.
9. **`int_promotion_baseline.sql` and `fact_promotions.sql` use a Postgres
   `LATERAL` + `generate_series` join to explode each promotion's own
   date range row-wise.** This is intentionally Postgres-specific (documented
   inline in both files) — a Snowflake deployment needs this rewritten
   (Snowflake's table generators don't support this exact per-row pattern).
   Do not "fix" this by trying to make it dialect-generic without a plan for
   the Snowflake side.
10. **The API (`api/`) never queries the warehouse's `landing` schema, only
    `marts`.** And the dashboard (`dashboard/`) never queries any database
    directly — only the API, via `dashboard/api_client.py`. Keep this
    layering; it's what the dbt exposures in `dbt/models/marts/_exposures.yml`
    document as the contract.
11. **`/sales/omnichannel` and `/shipments/reconciliation` are real,
    intentional additions beyond the original 10-endpoint API list**
    (documented inline in `api/models/sales.py` and `api/models/shipments.py`)
    — the dashboard's omnichannel and shipment-reconciliation pages have no
    other data source. Keep them; don't "simplify" the API back down to
    exactly 10 endpoints.

## 7. Continuation Prompt (paste into a new Claude Code session)

```
Continue building the CPG Pulse project at
C:\Users\sande\Indu-Docs\Projects\cpg-pulse. Phases 1-7 are complete and
were live-validated in a previous session (real Postgres, real API server,
real browser screenshots of the dashboard) -- read docs/checklist.md for
the full evidence trail and docs/remaining_work.md for exactly what's left,
known limitations, and architectural decisions you must not change.

Start by reading docs/remaining_work.md in full, then docs/checklist.md,
then docs/architecture.md. Do not re-implement anything already marked done
in docs/checklist.md.

Continue with Phase 8 (testing) first, then Phase 9 (CI/CD), then Phase 10
(documentation), in that order, matching docs/remaining_work.md section 2's
priority list. Validate each phase live (run the actual tests / actual CI
config / actual generated docs) before moving to the next, the same way the
previous session did -- don't just write code and assume it works, actually
run it and show the output, the same rigor documented throughout
docs/checklist.md.

Docker's daemon was not available in the previous session, so Docker Compose
was never actually run end-to-end, and PySpark could not run on this Windows
host (worker crashes under Python 3.12 regardless of JDK version -- a known
Windows/Spark friction, not a code defect). If Docker/Spark work in this
session, that's the first thing worth actually trying, since it would let
you validate the parts of Phase 4/8 that the previous session could only
code-review. If they still don't work, keep using the isolated-local-Postgres
+ bare-process approach documented in docs/remaining_work.md section 3
(a throwaway Postgres cluster via initdb/pg_ctl, kept separate from any
pre-existing local Postgres on this machine) -- it worked well.

Move through the phases continuously without stopping for approval between
them, same as the previous session did. Ask me only if you hit a genuine
ambiguity docs/remaining_work.md doesn't resolve.
```

---
*End of handoff. See `docs/checklist.md` for the detailed, phase-by-phase
build log this document summarizes.*
