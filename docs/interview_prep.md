# CPG Pulse - Resume Bullets & Interview Prep

Grounded entirely in what was actually built and actually validated in this
project (see `docs/checklist.md` for the evidence trail behind every claim
here) - no invented percentages, no claims beyond what was verified.

## Resume Bullets

Pick 3-5 depending on the role; don't use all of them at once.

- Designed and built an end-to-end CPG data platform (synthetic data
  generation → PySpark standardization → dbt-modeled Snowflake/Postgres
  warehouse → FastAPI → Streamlit) spanning 9 heterogeneous source systems
  with retailer-specific identifiers conformed to a canonical product/store
  key space via SCD Type 2 dimensional modeling.
- Implemented a config-driven data-quality engine (custom, in-house - a
  deliberate alternative to Great Expectations after evaluating its
  dependency footprint against the project's constraints) with 3 YAML
  expectation suites covering null checks, range checks, uniqueness,
  referential integrity, freshness, and volume-anomaly detection.
- Built a dimensional warehouse with dbt: 38 models across staging,
  intermediate, and marts layers, 2 SCD Type 2 snapshots, 89 automated
  tests - validated live against a real Postgres warehouse, including
  proving SCD2 correctness by mutating source data and confirming the
  history split as expected.
- Diagnosed and fixed a data-reproducibility bug where Python's built-in
  `hash()` (salted per-process) was silently breaking a synthetic data
  generator's seeded reproducibility guarantee; replaced with `hashlib` and
  added a regression test.
- Wrote 204 automated tests (unit, integration, data-quality, API, dbt)
  achieving real coverage of idempotency, late-arriving-data handling,
  schema-drift detection, and duplicate/invalid-record handling - caught
  and fixed two production-shaped bugs *by writing the tests*, not just
  before them: a backfill silently regressing an ingestion watermark
  backward, and a dbt build-order dependency that only failed on a
  genuinely fresh database.
- Built a FastAPI service (12 endpoints, service-layer architecture,
  pagination, input validation, structured error handling) and a 6-page
  Streamlit dashboard, both validated live - including using a headless
  browser (Playwright) to screenshot every dashboard page and confirm real
  data rendered correctly, which is how a data-type bug (a UPC silently
  becoming a `bigint` through a CSV→pandas→Postgres round-trip) was caught.
- Documented a promotion-effectiveness estimation methodology (baseline-vs.
  actual comparison) with explicit causal-inference caveats, and empirically
  validated its sample-size sensitivity by regenerating a longer test
  dataset and confirming the estimated lift converged toward the synthetic
  data's known ground-truth range.

## Interview Q&A

**Q: Walk me through the architecture.**
A: Layered lake (raw → standardized → curated) feeding a dbt-modeled
warehouse (staging → intermediate → marts), served through a FastAPI layer
that the dashboard consumes - never the warehouse directly. The raw layer is
a byte-exact copy of whatever the source sends; standardization is where
canonical IDs, type casting, and deduplication happen; curated is
DQ-checked. Local dev runs the exact same code against MinIO/Postgres that
production would run against S3/Snowflake - only endpoint config changes.

**Q: How did you handle the fact that every retailer uses its own product
IDs?**
A: A `retailer_product_mapping` table maps each retailer's SKU to the
canonical `product_id`, with effective-dated history - retailers do
periodically re-platform and reissue their own SKUs, so this needed to be a
real SCD Type 2 concept at the source, not a simple lookup table. The join
that resolves a transaction's `retailer_product_id` to `product_id` has to
be date-aware (`transaction_date BETWEEN effective_start_date AND
effective_end_date`), or a historical remap would silently misattribute old
sales to the wrong product.

**Q: Tell me about a bug you found and how.**
A: Two good examples, both found by actually running things, not by
inspection. First: `/products` was 500ing. Traced it through the API's
Pydantic model (which correctly required `str` for a UPC) down through
`dim_product`, down through a dbt snapshot that - I discovered - was reading
straight from the raw source table instead of the type-cast staging model,
which is why the UPC came through as a `bigint` some of the time (a CSV →
pandas → Postgres round-trip infers numeric-looking strings as numbers).
Fixed by routing the snapshot through staging instead, and the underlying
lesson generalizes: SCD2 snapshots should always read from a
cleaning/staging layer, never raw source, exactly for this reason.

Second: I wrote a test asserting that a backfill for an old date range
shouldn't disturb the pipeline's main watermark, expecting it to pass
(the architecture doc already said backfills shouldn't touch the
watermark) - and it failed. The actual `set_watermark` call had no
special-casing for backfills, so backfilling old data would silently move
the watermark *backward*, which would cause the next normal run to
rediscover and re-land a bunch of already-processed data. Fixed with a
one-line guard, caught entirely because I wrote the test the architecture
doc implied should already be true, instead of assuming it was.

**Q: How do you know your promotion lift numbers are trustworthy?**
A: I don't claim they always are, and the docs say so explicitly. The
lift estimate compares actual promo-period sales to a baseline built from
8 weeks of pre-promotion history. On a short test dataset, most promotions
didn't have 8 full weeks of history available, and the resulting lift
numbers were absurd (some over 2000%). I regenerated a longer dataset,
confirmed which promotions actually got the full lookback window, and for
those the median estimated lift was ~117% - which lines up well with the
40-180% true lift range I'd built into the synthetic data generator. So the
methodology is sound *given enough history*; I made sure that caveat is
documented everywhere the metric is surfaced (API docstring, dashboard page,
`docs/metrics.md`), not just known to me.

**Q: What would you do differently at production scale?**
A: A few things: real Kafka/CDC for near-real-time POS instead of daily
batch files, if the business need justified it - this design assumed daily
batch because that's how most CPG-retailer EDI integrations actually work,
not because streaming is hard. I'd also move the promotion-baseline
calculation to use a proper control-group design (matched comparable
stores) rather than a pre/post comparison, if the lift numbers were going to
drive real trade-spend decisions rather than directional prioritization.
And I'd finish the PySpark standardization jobs for the sources that only
have a local-dev fallback today (shipments, promotions, e-commerce) - the
pattern's established, it just wasn't the highest-priority thing given the
time available.

**Q: Why dbt instead of hand-written SQL/stored procedures?**
A: Version-controlled transformations with built-in testing (89 tests here),
free lineage/documentation, and - the concrete case that mattered most in
this project - snapshots as a clean, standard way to implement SCD Type 2
without hand-rolling the merge logic. It also cleanly separates "what changed
between environments" (just the `profiles.yml` target) from "what the
transformation logic is," which is exactly what let the same dbt project
target a local Postgres warehouse and document a real-Snowflake target
without duplicating any model code.

**Q: How did you validate this without a full production environment?**
A: Docker's daemon wasn't available in my dev sandbox, so I stood up an
isolated, throwaway local Postgres cluster (kept deliberately separate from
any pre-existing local Postgres) via `initdb`/`pg_ctl`, and ran everything -
ingestion, dbt, the API, the dashboard - against that for real. I was
explicit in the documentation about exactly what that did and didn't prove
(e.g., it proves the SQL and Python logic are correct; it doesn't prove the
actual Docker images build and run, which I could only verify by inspection
of the Dockerfiles and `docker-compose.yml`'s build contexts). Being precise
about the boundary between "actually verified" and "reviewed but not run" is
itself part of the discipline - see `docs/remaining_work.md` and
`docs/checklist.md` for exactly where that line falls throughout the project.
