#!/usr/bin/env python
"""Loads curated data into the warehouse's `landing` schema -- the local
Postgres equivalent of the "Snowflake Loading" step (Airflow DAG #9 in
docs/architecture.md). dbt's staging models (dbt/models/staging/) read from
`landing.*` via dbt/models/staging/sources.yml; nothing upstream of this
script is dbt's concern.

Two data paths, chosen automatically per source:

1. **Real pipeline path**: if `data/lake/curated/<source>/` parquet exists
   (i.e. spark/jobs/run_quality_checks.py has actually run), load it as-is --
   it is already standardized, canonical-ID-resolved, and DQ-passed.
2. **Local-dev fallback path**: if not, read straight from
   `data/generated/<source>/` and apply a minimal pandas-based stand-in for
   Spark standardization (canonical ID resolution via retailer_product_mapping,
   drop unresolvable rows) so the dbt project is still exercisable end-to-end
   without a working local Spark/Java setup. This is clearly a development
   convenience, not a second source of truth -- see docs/runbook.md.

Reference tables (product_master, store_master, retailer_product_mapping,
retailers, distribution_centers, calendar, promotions) need no
transformation either way and load directly from data/generated/.

pipeline_meta.dq_results / pipeline_runs are copied from the metadata
Postgres database into landing.dq_results / landing.pipeline_runs, since dbt
only has one target database -- this is what lets fact_data_quality_results
be modeled as a normal dbt mart despite the metadata store being a physically
separate database from the warehouse (docs/architecture.md section 4).

Usage:
    python scripts/load_to_warehouse.py
    python scripts/load_to_warehouse.py --generated-dir data/sample
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("load_to_warehouse")

REFERENCE_SOURCES = [
    "retailers", "distribution_centers", "product_master", "store_master",
    "retailer_product_mapping", "calendar", "promotions",
]
TRANSACTIONAL_SOURCES = ["retail_pos_sales", "retail_inventory", "manufacturer_shipments", "ecommerce_orders"]

BUSINESS_DATE_COL = {
    "retail_pos_sales": "transaction_date",
    "retail_inventory": "snapshot_date",
    "manufacturer_shipments": "shipment_date",
    "ecommerce_orders": "order_date",
}
BUSINESS_KEY = {
    "retail_pos_sales": ["retailer_id", "store_id", "retailer_product_id", "transaction_date", "sales_channel"],
    "retail_inventory": ["retailer_id", "store_id", "retailer_product_id", "snapshot_date"],
    "manufacturer_shipments": ["shipment_id"],
    "ecommerce_orders": ["order_id"],
}


def warehouse_engine():
    from sqlalchemy import create_engine

    host = os.environ.get("WAREHOUSE_DB_HOST", "localhost")
    port = os.environ.get("WAREHOUSE_DB_PORT", "5432")
    dbname = os.environ.get("WAREHOUSE_DB_NAME", "cpg_pulse_warehouse")
    user = os.environ.get("WAREHOUSE_DB_USER", "cpgpulse")
    password = os.environ.get("WAREHOUSE_DB_PASSWORD", "")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}")


def metadata_engine():
    from sqlalchemy import create_engine

    host = os.environ.get("METADATA_DB_HOST", "localhost")
    port = os.environ.get("METADATA_DB_PORT", "5432")
    dbname = os.environ.get("METADATA_DB_NAME", "cpg_pulse_metadata")
    user = os.environ.get("METADATA_DB_USER", "cpgpulse")
    password = os.environ.get("METADATA_DB_PASSWORD", "")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}")


def _coerce_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Any `*_date` column gets parsed to a real datetime dtype, even if every
    value in this particular load happens to be null. Without this, a column
    that is *entirely* null in a given batch (e.g. `closing_date` when none of
    the ~8 stores in a small sample happen to be closed) gets inferred by
    pandas as float64, and pandas.to_sql then creates it as `double precision`
    in Postgres -- which downstream staging SQL can't cast to `date`. This bit
    a real run during Phase 5 development against the small sample dataset.
    """
    for col in df.columns:
        if col.endswith("_date") or col == "date":
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _replace_table(df: pd.DataFrame, table: str, engine, schema: str = "landing") -> None:
    """Load-full-replace a landing table. Plain `df.to_sql(if_exists='replace')`
    issues a bare `DROP TABLE`, which fails once dbt has run at least once and
    created staging views on top of these tables (a real error hit during
    Phase 5 development: `DependentObjectsStillExist`). Dropping with CASCADE
    first is the correct behavior here -- landing is a reload-in-full staging
    area by design, and `dbt run` recreates the dependent views on the next
    run regardless.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'))
    df.to_sql(table, engine, schema=schema, if_exists="append", index=False)


def _read_any_format(root: Path) -> pd.DataFrame:
    """Read every file of whichever format is present under `root`, recursively
    (handles both a flat reference-dataset folder and a partitioned
    extract_date=.../ transactional folder)."""
    for fmt, reader in (("csv", pd.read_csv), ("parquet", pd.read_parquet), ("json", pd.read_json)):
        files = sorted(glob.glob(str(root / fmt / "**" / f"*.{fmt}"), recursive=True))
        if files:
            frames = [reader(f) for f in files]
            return _coerce_date_columns(pd.concat(frames, ignore_index=True))
    raise FileNotFoundError(f"No data files found under {root}")


def load_reference_tables(generated_dir: str, engine) -> None:
    for source in REFERENCE_SOURCES:
        root = Path(generated_dir) / source
        if not root.exists():
            logger.warning("skipping %s -- %s does not exist (run scripts/generate_synthetic_data.py first)", source, root)
            continue
        df = _read_any_format(root)
        _replace_table(df, source, engine)
        logger.info("loaded landing.%s: %d rows", source, len(df))


def _fallback_standardize(source: str, raw_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    """Minimal pandas stand-in for spark/jobs/standardize_*.py, used only when
    the real curated Parquet output doesn't exist yet. Resolves
    retailer_product_id -> product_id (SCD2-aware on effective dates) and
    drops rows that can't be resolved -- deliberately simpler than the real
    Spark jobs (no quarantine-with-reason, no store validation), since this
    path exists purely so the dbt project has something to build against.
    """
    date_col = BUSINESS_DATE_COL[source]
    df = raw_df.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.date

    if source == "retail_inventory":
        # Mirrors spark/transformations/common.py::rename_columns: pre-schema-
        # change files call this column reserved_qty (see
        # scripts/data_gen/quality_issues.py). Reconcile both possible names
        # into the canonical reserved_units before anything downstream (dbt
        # staging) has to know this rename ever happened.
        if "reserved_qty" in df.columns and "reserved_units" in df.columns:
            df["reserved_units"] = df["reserved_units"].combine_first(df["reserved_qty"])
            df = df.drop(columns=["reserved_qty"])
        elif "reserved_qty" in df.columns:
            df = df.rename(columns={"reserved_qty": "reserved_units"})

    if source in ("manufacturer_shipments", "ecommerce_orders"):
        # Both are already keyed on the canonical product_id, not a
        # retailer-specific identifier: manufacturer_shipments is an internal
        # ERP feed, and ecommerce_orders is CPG Pulse's own DTC storefront --
        # neither goes through a retailer's product mapping. See
        # docs/data_dictionary.md.
        resolved = df
    else:
        mapping = mapping_df.copy()
        mapping["effective_start_date"] = pd.to_datetime(mapping["effective_start_date"]).dt.date
        mapping["effective_end_date"] = pd.to_datetime(mapping["effective_end_date"]).dt.date

        merged = df.merge(mapping, on=["retailer_id", "retailer_product_id"], how="left", suffixes=("", "_map"))
        in_range = (
            merged["effective_start_date"].isna()
            | (merged[date_col] >= merged["effective_start_date"])
        ) & (
            merged["effective_end_date"].isna() | (merged[date_col] <= merged["effective_end_date"])
        )
        resolved = merged[in_range & merged["product_id"].notna()].copy()
        resolved = resolved.drop(columns=["effective_start_date", "effective_end_date", "match_method", "match_confidence", "retailer_product_description"], errors="ignore")

    key_cols = BUSINESS_KEY[source]
    before = len(resolved)
    resolved = resolved.drop_duplicates(subset=key_cols, keep="last")
    dropped = before - len(resolved)
    if dropped:
        logger.info("[%s] fallback standardize: dropped %d unresolved/duplicate rows out of %d", source, dropped, before)
    return resolved


def load_transactional_tables(generated_dir: str, engine) -> None:
    mapping_df = _read_any_format(Path(generated_dir) / "retailer_product_mapping")

    for source in TRANSACTIONAL_SOURCES:
        curated_path = Path("data/lake/curated") / source
        if curated_path.exists():
            df = pd.read_parquet(curated_path)
            logger.info("[%s] loaded from real curated layer: %d rows", source, len(df))
        else:
            raw_root = Path(generated_dir) / source
            if not raw_root.exists():
                logger.warning("skipping %s -- no curated output and no generated data found", source)
                continue
            raw_df = _read_any_format(raw_root)
            df = _fallback_standardize(source, raw_df, mapping_df)
            logger.info("[%s] loaded via local-dev fallback standardize: %d rows", source, len(df))

        _replace_table(df, source, engine)


def load_pipeline_metadata(engine, meta_engine) -> None:
    try:
        dq_results = pd.read_sql("SELECT * FROM pipeline_meta.dq_results", meta_engine)
        _replace_table(dq_results, "dq_results", engine)
        logger.info("loaded landing.dq_results: %d rows", len(dq_results))

        pipeline_runs = pd.read_sql("SELECT * FROM pipeline_meta.pipeline_runs", meta_engine)
        _replace_table(pipeline_runs, "pipeline_runs", engine)
        logger.info("loaded landing.pipeline_runs: %d rows", len(pipeline_runs))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load pipeline metadata (is the metadata DB reachable?): %s", exc)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=str, default="data/generated")
    args = parser.parse_args(argv)

    generated_dir = args.generated_dir
    if not Path(generated_dir).exists():
        fallback = "data/sample"
        logger.warning("%s does not exist -- falling back to %s", generated_dir, fallback)
        generated_dir = fallback

    engine = warehouse_engine()
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS landing"))

    load_reference_tables(generated_dir, engine)
    load_transactional_tables(generated_dir, engine)
    load_pipeline_metadata(engine, metadata_engine())
    logger.info("Warehouse landing load complete.")


if __name__ == "__main__":
    main()
