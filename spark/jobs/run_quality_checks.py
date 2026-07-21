#!/usr/bin/env python
"""Data-quality validation job: runs the declarative expectation suites
(spark/quality/expectations/*.yml) against the **standardized** layer,
records every check result to `pipeline_meta.dq_results` (this table is what
`fact_data_quality_results` in the warehouse is built from), writes a
human-readable JSON report per run, and promotes the data to the curated
layer.

This is deliberately a separate pipeline step from standardization (matching
the 12-DAG list in docs/architecture.md: "PySpark standardization" and
"Data-quality validation" are different DAGs): standardization already
quarantined rows that can't be conformed at all (unresolved product ID,
negative units, ...); this step runs *aggregate* checks (uniqueness,
freshness, volume-anomaly, accepted values) that only make sense across the
whole batch, and are alerts/visibility rather than additional row-level
filtering -- a freshness or volume-anomaly failure should page someone, not
silently drop data.

Usage:
    python spark/jobs/run_quality_checks.py --source retail_pos_sales
    python spark/jobs/run_quality_checks.py --source retail_inventory
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.common import db
from spark.quality import dq_engine
from spark.utilities.paths import layer_path
from spark.utilities.spark_session import get_spark_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_quality_checks")

SUITE_BY_SOURCE = {
    "retail_pos_sales": "pos_sales_suite",
    "retail_inventory": "inventory_suite",
    "promotions": "promotions_suite",
}

DATE_COL_BY_SOURCE = {
    "retail_pos_sales": "transaction_date",
    "retail_inventory": "snapshot_date",
}


def _trailing_average_count(spark, source_name: str, date_col: str, current_count: int) -> int | None:
    """Trailing-7-day average row count from the curated layer, used as the
    volume-anomaly baseline. Returns None (skip the check) if there isn't
    enough curated history yet -- e.g. the very first run for a source.
    """
    curated_path = layer_path("curated", source_name)
    try:
        existing = spark.read.parquet(curated_path)
    except Exception:
        return None
    if existing.rdd.isEmpty():
        return None
    from pyspark.sql import functions as F

    daily_counts = existing.groupBy(date_col).count().orderBy(F.col(date_col).desc()).limit(7)
    rows = daily_counts.collect()
    if not rows:
        return None
    return int(sum(r["count"] for r in rows) / len(rows))


def run(source_name: str) -> dict:
    spark = get_spark_session(f"dq_{source_name}")
    suite_name = SUITE_BY_SOURCE[source_name]

    standardized_path = layer_path("standardized", source_name)
    df = spark.read.parquet(standardized_path)
    if df.rdd.isEmpty():
        logger.info("no standardized data for %s -- nothing to validate", source_name)
        return {"status": "SKIPPED"}

    date_col = DATE_COL_BY_SOURCE.get(source_name)
    trailing_avg = _trailing_average_count(spark, source_name, date_col, df.count()) if date_col else None

    results = dq_engine.run_suite(df, suite_name, trailing_avg_count=trailing_avg)
    report_path = dq_engine.write_report(suite_name, results)

    pass_rate = sum(r.passed for r in results) / len(results)
    logger.info("[%s] DQ suite complete: %d/%d checks passed, report=%s", source_name, sum(r.passed for r in results), len(results), report_path)

    with db.connection_scope() as conn:
        run_id = db.start_run(conn, dag_id="data_quality_validation", task_id=f"dq_{source_name}", source_name=source_name, run_type="DATA_QUALITY")
        conn.commit()
        for result in results:
            db.log_dq_result(
                conn, run_id, table_name=source_name, check_name=result.name, check_category=result.category,
                passed=result.passed, records_checked=result.records_checked, records_failed=result.records_failed,
                failure_detail=result.detail,
            )
        db.finish_run(conn, run_id, status="SUCCEEDED", records_read=df.count(), records_valid=df.count())
        conn.commit()

    # Promote to curated: row-level validity was already enforced during
    # standardization, so this suite's role is aggregate visibility, not an
    # additional filter -- the whole standardized batch is promoted regardless
    # of individual check outcomes (a failed freshness/volume check should
    # alert, not silently withhold today's data from the warehouse).
    partition_col = date_col or df.columns[0]
    df.write.mode("overwrite").option("partitionOverwriteMode", "dynamic").partitionBy(partition_col).parquet(
        layer_path("curated", source_name)
    )

    return {"status": "SUCCEEDED", "pass_rate": pass_rate, "report_path": str(report_path)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=list(SUITE_BY_SOURCE.keys()))
    args = parser.parse_args(argv)
    result = run(args.source)
    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()
