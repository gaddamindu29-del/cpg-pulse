# CPG Pulse - Operations Runbook

Practical, day-to-day operational guidance: how to run each stage, what to
check when something's wrong, and every "known quirk" documented inline in
the codebase, consolidated in one place. For what's built vs. not, see
`docs/checklist.md`; for architectural decisions, see
`docs/remaining_work.md` §6.

---

## 1. Standing Up the Environment

```bash
make setup      # .env from .env.example, pip install -r requirements.txt
make up         # docker compose up -d --build: Postgres, MinIO, Airflow
make seed       # apply metadata schema + create MinIO buckets (idempotent)
```

`make up` **has been run end-to-end for real** (Postgres, MinIO, Airflow
init/scheduler/webserver, API, dashboard all confirmed healthy), after fixing
three real bugs the first time a Docker daemon was actually available to
build against:

1. `airflow/Dockerfile` had a typo: `--no-install-recursive` isn't a valid
   `apt-get` flag (should be `--no-install-recommends`).
2. `airflow/requirements-airflow.txt` pinned `boto3`/`pandas`/`pyarrow`/
   `psycopg2-binary` to versions that conflict with Airflow's own pinned
   `--constraint` file (`pip install --constraint` hard-fails, not warns, on
   any conflict). Fixed by unpinning all four and letting the constraints
   file win, since they're all in Airflow's own dependency closure anyway.
3. The image shipped with **no JDK and no `pyspark` at all** - the "run Spark
   jobs inside this container" plan was documented throughout the project but
   never actually implemented at the Dockerfile level, since no Docker daemon
   existed to catch the gap until now. Fixed by adding `default-jdk-headless`
   + `JAVA_HOME`/`PATH` to `airflow/Dockerfile`, and `PyYAML` + unpinned
   `pyspark` to `airflow/requirements-airflow.txt`. See §4 for the resulting
   PySpark validation.

`docker-compose.yml`'s Postgres port is `${POSTGRES_HOST_PORT:-5432}` rather
than a bare `5432:5432` - a real conflict was hit locally against a
pre-existing host Postgres on the default port (two processes bound to 5432
simultaneously per `netstat`). Set `POSTGRES_HOST_PORT` in `.env` if you have
the same issue; service-to-service traffic inside the Docker network always
uses `postgres:5432` regardless of this value. Note also: `docker compose`
merges `ports:` lists **across** compose files (including override files)
rather than replacing them - an override file that only changes the host
port will leave the base file's mapping active too, which is a real risk if
that base mapping collides with something already running on your host.

If Airflow's `airflow-init` step hangs, check its logs specifically (it runs
`airflow db migrate` + creates the admin user, and is the slowest first-boot
step). Note that `airflow-init`, `airflow-scheduler`, and `airflow-webserver`
each build their **own** separate image from the same `airflow/Dockerfile`
(no explicit `image:` name in `docker-compose.yml` means Compose tags them
per-service) - after changing the Dockerfile or its requirements file, run
`docker compose build` for all three, not just the one you're about to use.

## 2. Generating Data

```bash
python scripts/generate_synthetic_data.py                       # full run: ~4 min, ~1.6GB, ~3.85M POS rows
python scripts/generate_synthetic_data.py --start-date 2025-01-01 --end-date 2025-02-28 \
  --num-products 12 --stores-per-retailer "RTL-WMT=3,RTL-TGT=2,RTL-KRG=2,RTL-AMZ=1" \
  --output-dir data/sample                                       # small sample (committed to git)
```

**Quirk**: the reserved_qty→reserved_units schema-change scenario (see §4)
only occurs after `2025-09-01`. A short-range generation (like the default
`data/sample`) never crosses that boundary - you'll need a full-range run
(or at least one extending past September 2025) to exercise it.

**Quirk**: promotion lift figures are unreliable on short-range data - the
8-week baseline lookback (`promotion_baseline_lookback_weeks` dbt var) needs
at least that much history *before* a promotion to produce a trustworthy
estimate. See `docs/metrics.md`'s Promotion Lift section for the full
explanation (this was empirically verified, not just theorized).

## 3. Running Ingestion

```bash
python -m ingestion.retailer_sales.ingest
python -m ingestion.inventory.ingest
python -m ingestion.shipments.ingest
python -m ingestion.promotions.ingest
python -m ingestion.ecommerce.ingest
python -m ingestion.product_master.ingest    # also loads store_master, retailer_product_mapping, retailers, distribution_centers, calendar

# Backfill a specific date range (does NOT disturb the normal watermark --
# see §5 for why this matters):
python -m ingestion.retailer_sales.ingest --backfill-start 2025-01-01 --backfill-end 2025-01-31
```

Each run writes one row to `pipeline_meta.pipeline_runs` (queryable via the
API's `/pipeline-runs` endpoint or the dashboard's Ops page) and logs any
schema drift to `pipeline_meta.schema_change_log`.

**To check if ingestion actually did anything**: a `SKIPPED` status with
`files_landed=0` is not a failure - it means the watermark is already caught
up. Only investigate if you expected new data and got `SKIPPED`.

## 4. Running Standardization (PySpark)

```bash
python spark/jobs/standardize_pos_sales.py
python spark/jobs/standardize_inventory.py
python spark/jobs/run_quality_checks.py --source retail_pos_sales
python spark/jobs/run_quality_checks.py --source retail_inventory
```

**⚠️ Environment-dependent - but now confirmed working.** These cannot run in
this project's Windows development environment directly - Spark 3.5.1's
Python worker process crashes under Python 3.12 on Windows regardless of JDK
version (17 and 23 both tried, both fail identically with `EOFException` /
"Python worker exited unexpectedly"). This is a known class of Windows-native
PySpark friction, not a defect in the job code. **Run these inside the
Docker `airflow-scheduler` container** (Linux, Python 3.11, `default-jdk-headless`)
- confirmed working for real: all four jobs above were run against the full
generated dataset (3,854,199 raw POS rows / 582,777 raw inventory rows),
producing 3,761,605 / 575,312 valid standardized+curated rows respectively,
with the rest correctly quarantined by business rule. The Docker image
originally shipped with *no* JDK and no `pyspark` at all - `airflow/Dockerfile`
had to be fixed to add `default-jdk-headless` + `JAVA_HOME`, and
`airflow/requirements-airflow.txt` to unpin `pyspark` (see §8 below) before
any of this worked. If you hit the Windows crash signature on Linux too:

```
py4j.protocol.Py4JJavaError: ... Python worker exited unexpectedly (crashed)
Caused by: java.io.EOFException
```

check `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` point at a real interpreter -
the same class of "wrong Python resolved" issue can happen with venvs even on
Linux.

Only `standardize_pos_sales.py` and `standardize_inventory.py` exist -
shipments/promotions/ecommerce standardization jobs were never built (see
`docs/checklist.md` Phase 4). The pattern to extend is fully established in
those two files plus `spark/transformations/common.py`.

## 5. Loading the Warehouse

```bash
python scripts/load_to_warehouse.py                              # uses data/generated/ + real curated parquet if present
python scripts/load_to_warehouse.py --generated-dir data/sample  # small/fast, for local dev
```

Two paths, chosen automatically per source (see
`docs/source_to_target_mapping.md` for the full breakdown):
1. **Real pipeline path**: if `data/lake/curated/<source>/` parquet exists
   (Spark actually ran), loads it as-is.
2. **Local-dev fallback path**: otherwise, reads straight from
   `data/generated/<source>/` and applies a minimal pandas stand-in for
   Spark standardization. **This is a documented convenience, not a second
   source of truth** - if Spark works in your environment, prefer path 1.

**Quirk**: an entirely-null date column in a small batch (e.g. `closing_date`
when none of your generated stores happen to be closed) gets inferred as
`float64` by pandas, which Postgres can't cast to `date`. Already fixed
(`_coerce_date_columns()` in `load_to_warehouse.py`) - don't remove that
function.

**Quirk**: re-running this script after `dbt run` has already created views
on top of the `landing` tables will fail with `DependentObjectsStillExist`
unless the loader does a `DROP TABLE ... CASCADE` first. Already fixed
(`_replace_table()`) - don't revert to a plain `df.to_sql(if_exists='replace')`.

**Real bug (found during Docker validation) #1 - OOM on the full dataset**:
loading `retail_pos_sales`'s curated layer (3.76M rows across 8k+ Parquet
files) via a single `pd.read_parquet(curated_path)` + one unbounded `to_sql()`
call OOM-killed the Docker container outright (`docker inspect` showed
`OOMKilled: true`; the Python process itself vanished mid-run with no
traceback - nothing in `stdout`/`stderr`, just silently gone). Small/sample
datasets never hit this. Fixed by streaming the curated directory in
row-batches via `pyarrow.dataset` (`_iter_curated_batches()` /
`_replace_table_streamed()`) instead of materializing the whole table in
memory at once.

**Real bug (found during Docker validation) #2 - the streaming fix silently
dropped the date column**: `spark/jobs/run_quality_checks.py` writes curated
output with `.partitionBy(date_col)`, which - standard Spark/Hive behavior -
removes that column from the Parquet files themselves and encodes it only in
the directory names (`transaction_date=2025-01-01/...`). `pd.read_parquet(dir)`
reconstructs it automatically; the lower-level `pyarrow.dataset.dataset()`
used by the streaming fix above does **not**, unless told
`partitioning="hive"`. Without it, `landing.retail_pos_sales` loaded
successfully (no error) but silently had no `transaction_date` column at
all - caught when `dbt run` failed with `column "transaction_date" does not
exist` against a table that had just "successfully" loaded 3.76M rows. Fixed
by passing `partitioning="hive"` to `ds.dataset()`. **Lesson**: a clean load
with no errors doesn't prove the data is correct - always spot-check the
resulting schema/row content, not just the row count, especially after
touching the read path for partitioned Parquet.

## 6. Running dbt

```bash
cd dbt
export DBT_PROFILES_DIR=$(pwd)         # or copy profiles.yml.example -> ~/.dbt/profiles.yml
cp profiles.yml.example profiles.yml   # never commit the copy -- gitignored
dbt deps
dbt seed
dbt run --select staging    # MUST run before `dbt snapshot` -- see below
dbt snapshot
dbt run --exclude staging   # everything else: intermediate + marts
dbt test
dbt docs generate && dbt docs serve
```

**⚠️ Step order is not arbitrary.** `dim_product_snapshot`/`dim_store_snapshot`
select from `ref('stg_product_master')`/`ref('stg_store_master')` (the
staging *models*), not the raw `landing` source directly. Running
`dbt snapshot` before staging has ever been built fails with:
```
relation "staging.stg_store_master" does not exist
```
This exact failure was hit and fixed while writing `.github/workflows/ci.yml`
- a plain `dbt seed && dbt snapshot && dbt run` sequence (which is what an
earlier draft of this very runbook, and the CI workflow, both had) works
the *second* time you run it (because staging already exists from a prior
run) but fails from a genuinely fresh database. If you ever see this error,
this ordering issue is almost certainly why - run `dbt run --select staging`
first.

`make dbt-run` already encodes the correct sequence - use it instead of
raw `dbt run` if you just want "build everything."

## 7. Running the API and Dashboard

```bash
make api         # uvicorn api.main:app --reload --port 8000  (http://localhost:8000/docs)
make dashboard   # streamlit run dashboard/app.py               (http://localhost:8501)
```

The dashboard needs `DASHBOARD_API_BASE_URL` pointing at a running API
(default `http://localhost:8000`; the Docker Compose `dashboard` service sets
it to `http://api:8000`). If dashboard pages show "Could not load data from
the API," check the API is actually up (`curl http://localhost:8000/health`)
before checking the warehouse.

**Empty states are expected, not bugs**: `/data-quality/latest` and the
dashboard's DQ page will be empty until `spark/jobs/run_quality_checks.py`
has actually run (see §4's Spark caveat) - both handle this gracefully
(confirmed via screenshot during Phase 7 validation), they don't crash.

## 8. Running Tests

```bash
pytest tests/unit/test_generator.py -v          # 38 tests
pytest tests/unit/test_ingestion_common.py -v   # 18 tests, fully isolated (no DB needed)
pytest tests/integration/ -v                    # 16 tests (7 fake-DB, 9 need a real warehouse -- skip cleanly if unreachable)
pytest tests/data_quality/ -v                   # 15 tests (10 real, 5 skip without working Spark -- see §4)
pytest api/tests/ -v                            # 28 tests, needs a real warehouse
cd dbt && dbt test                              # 89 tests
```

Full count: **204 tests, 199 passing + 5 documented Spark skips** as of this
writing (see `docs/checklist.md` Phase 8 for the full breakdown). None
require mocking the database for anything that's actually SQL/warehouse
behavior - `tests/conftest.py::warehouse_engine` skips cleanly (not
falsely-green) if no database is reachable. The 5 Spark skips run for real
inside Docker (see §4) but still skip on a bare host with no working Spark.

**⚠️ Never run `tests/integration/test_ingestion.py` against a working
directory that holds real pipeline output you care about.** Its
`clean_lake_state` fixture does `shutil.rmtree(data/lake)` before *and*
after each test - correct behavior for a test fixture (each test needs a
clean slate), but a real near-miss happened during Docker validation: `pytest
tests/ api/tests/` was launched against a `data/lake` that had just taken
several hours of real Spark processing to produce, and the rmtree was
mid-flight (partially deleted `data/lake/curated/`) when it was caught and
killed. Recovered by re-running `spark/jobs/run_quality_checks.py` for both
sources, since `data/lake/standardized/` - its real source - was untouched
(only `curated/` is derived+overwritten by that job, so this is always safe
to redo). If you need to run the full suite against a directory with real
data in it, run everything except this one file first
(`--ignore=tests/integration/test_ingestion.py`), and only run that file
against a disposable/scratch checkout.

## 9. Backfilling

```bash
python -m ingestion.retailer_sales.ingest --backfill-start 2025-01-01 --backfill-end 2025-01-31
python spark/jobs/standardize_pos_sales.py --business-date-start 2025-01-01 --business-date-end 2025-01-31
```

Backfills are explicit and out-of-band: they never move the ingestion
watermark (a real bug where they did was caught and fixed by
`tests/integration/test_ingestion.py::TestLateArrivingData` - see
`docs/checklist.md` Phase 8). Standardization's `--business-date-*` flags
scope which partitions get overwritten (`incremental_strategy='delete+insert'`
at the dbt layer, and explicit partition-overwrite at the Spark layer) - a
backfill for January doesn't touch February's data.

## 10. Resetting the Local Environment

```bash
make clean-data   # rm -rf data/generated/* data/quarantine/* (data/sample/ is NOT touched -- it's source, not output)
make clean        # clean-data + docker compose down -v (DESTRUCTIVE: drops all volumes)
```

To reset just the warehouse without touching Docker volumes: drop and
recreate the `landing`/`staging`/`snapshots`/`marts` schemas, or simply
`DROP SCHEMA ... CASCADE` each and re-run `scripts/load_to_warehouse.py` +
the dbt sequence in §6.

## 11. Where to Look When Something's Wrong

| Symptom | Check |
|---|---|
| API returns 503 | `warehouse_reachable` field in `/health` - DB connectivity, not app logic |
| API returns 500 on a specific field | Likely a warehouse type mismatch reaching an under-typed Pydantic model - see the real `upc` bigint/text bug (`docs/remaining_work.md` #2) for the exact failure signature and fix pattern |
| Dashboard page blank/error | Check the API is reachable first (`curl .../health`), then check the specific mart the page reads from has data |
| `dbt snapshot` fails with "relation does not exist" | Staging wasn't built first - see §6 |
| Ingestion `SKIPPED` when you expected data | Watermark already caught up - check `pipeline_meta.watermarks`, or use `--backfill-start`/`--backfill-end` to force reprocessing regardless of watermark |
| Schema-change alert in `schema_change_log` | Check `is_breaking` - compatible changes (new optional columns) need no action; breaking changes (required column removed/retyped) mean standardization needs a corresponding fix (see the `reserved_qty`→`reserved_units` handling in `spark/transformations/common.py::rename_columns` as the template) |
| PySpark job crashes with `EOFException` | Windows/Python 3.12 host limitation, not a code bug - see §4 |
| Promotion lift numbers look absurd (1000%+) | Check `baseline_days` on the affected promotion - likely well under the 56-day target, meaning insufficient pre-period history, not a calculation error (see `docs/metrics.md`) |

## 12. Known Data-Realism Quirks (not bugs, but worth knowing)

- **Inventory snapshots are weekly, not daily**, in this synthetic dataset
  (`scripts/data_gen/simulate.py` generates one snapshot per week per
  product/store). "Days of supply" and stockout-risk calculations still work
  correctly at this cadence, but a stockout that happens and resolves within
  a week can be invisible between snapshots. A real daily-feed retailer would
  give finer-grained visibility.
- **Shipment-to-POS reconciliation is DC-level vs. store-level rolled up**
  to the same weekly grain - this can mask store-level gaps that net out
  across a retailer's whole footprint.
- **Data freshness checks will always report "stale"** if run against this
  project's fixed 2025 synthetic data, because they compare against
  wall-clock `today()`. This is correct behavior for the check, not a bug -
  freshness checks are only meaningful against live, continuously-arriving
  data.
