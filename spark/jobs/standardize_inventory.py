#!/usr/bin/env python
"""PySpark standardization job for retail inventory snapshots.

Same pattern as standardize_pos_sales.py, with one addition: this source has
a real mid-history column rename (`reserved_qty` -> `reserved_units`, injected
by scripts/data_gen/quality_issues.py to simulate a retailer feed change).
`common.rename_columns` reconciles both names into the canonical
`reserved_units` -- including the case where a late-arriving pre-change file
and an on-time post-change file land in the same extract_date partition and
a single raw batch contains both column names at once (see
docs/runbook.md "Known quirks").

Usage:
    python spark/jobs/standardize_inventory.py
    python spark/jobs/standardize_inventory.py --business-date-start 2025-01-01 --business-date-end 2025-01-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.sql import functions as F

from ingestion.common import db
from spark.transformations import canonical_ids, common
from spark.utilities.paths import layer_path
from spark.utilities.spark_session import get_spark_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("standardize_inventory")

SOURCE_NAME = "retail_inventory"
BUSINESS_KEY = ["retailer_id", "store_id", "retailer_product_id", "snapshot_date"]
COLUMN_ALIASES = {"reserved_qty": "reserved_units"}
TARGET_TYPES = {
    "snapshot_date": "date",
    "on_hand_units": "int",
    "on_order_units": "int",
    "reserved_units": "int",
    "available_units": "int",
}


def run(business_date_start: dt.date | None, business_date_end: dt.date | None) -> dict:
    spark = get_spark_session("standardize_inventory")
    batch_id = str(uuid.uuid4())

    raw_path = layer_path("raw", SOURCE_NAME)
    raw_df = common.read_raw(spark, raw_path, fmt="csv")
    if raw_df.rdd.isEmpty():
        logger.info("no raw data found at %s -- nothing to standardize", raw_path)
        return {"status": "SKIPPED", "records_read": 0}

    df = common.rename_columns(raw_df, COLUMN_ALIASES)
    # on_order_units has an injected null rate (scripts/data_gen/quality_issues.py);
    # treat a missing open-order count as zero rather than quarantining the row --
    # "no data reported" is not the same failure mode as "invalid record."
    if "on_order_units" in df.columns:
        df = df.withColumn("on_order_units", F.coalesce(F.col("on_order_units"), F.lit(0)))
    df = common.cast_columns(df, TARGET_TYPES)

    if business_date_start:
        df = df.filter(F.col("snapshot_date") >= F.lit(business_date_start.isoformat()))
    if business_date_end:
        df = df.filter(F.col("snapshot_date") <= F.lit(business_date_end.isoformat()))

    records_read = df.count()
    df = common.add_lineage_columns(df, batch_id)

    mapping_df = spark.read.option("header", "true").option("inferSchema", "true").csv(
        layer_path("raw", "retailer_product_mapping")
    )
    mapping_df = common.cast_columns(mapping_df, {"effective_start_date": "date", "effective_end_date": "date"})
    store_df = spark.read.option("header", "true").option("inferSchema", "true").csv(layer_path("raw", "store_master"))
    store_df = common.cast_columns(store_df, {"opening_date": "date", "closing_date": "date"})

    df = canonical_ids.resolve_product_id(df, mapping_df, business_date_col="snapshot_date")
    df = canonical_ids.validate_store(df, store_df, business_date_col="snapshot_date")
    df = common.deduplicate(df, BUSINESS_KEY)

    invalid_condition = (
        F.col("product_id").isNull()
        | (~F.col("store_valid"))
        | F.col("on_hand_units").isNull()
        | (F.col("on_hand_units") < 0)
        | (F.col("available_units") < 0)
        # inventory-calculation consistency: available should never exceed on_hand
        | (F.col("available_units") > F.col("on_hand_units"))
    )

    def reason_expr():
        return (
            F.when(F.col("product_id").isNull(), F.lit("UNRESOLVED_RETAILER_PRODUCT_ID"))
            .when(~F.col("store_valid"), F.lit("INVALID_OR_CLOSED_STORE"))
            .when(F.col("on_hand_units").isNull() | (F.col("on_hand_units") < 0), F.lit("NEGATIVE_OR_NULL_ON_HAND_UNITS"))
            .when(F.col("available_units") < 0, F.lit("NEGATIVE_AVAILABLE_UNITS"))
            .when(F.col("available_units") > F.col("on_hand_units"), F.lit("AVAILABLE_EXCEEDS_ON_HAND_INCONSISTENCY"))
            .otherwise(F.lit("UNKNOWN"))
        )

    invalid_df = df.filter(invalid_condition).withColumn("rejection_reason", reason_expr())
    valid_df = df.filter(~invalid_condition).drop("store_valid")

    valid_count = valid_df.count()
    invalid_count = invalid_df.count()

    common.write_standardized(valid_df, layer_path("standardized", SOURCE_NAME), partition_col="snapshot_date")
    common.write_quarantine(invalid_df, layer_path("quarantine", SOURCE_NAME), partition_col="snapshot_date")

    logger.info(
        "standardize_inventory: read=%d valid=%d invalid=%d (batch_id=%s)",
        records_read, valid_count, invalid_count, batch_id,
    )

    with db.connection_scope() as conn:
        run_id = db.start_run(
            conn, dag_id="pyspark_standardization", task_id="standardize_inventory",
            source_name=SOURCE_NAME, run_type="STANDARDIZATION",
        )
        conn.commit()
        db.finish_run(
            conn, run_id, status="SUCCEEDED", records_read=records_read,
            records_valid=valid_count, records_rejected=invalid_count, records_inserted=valid_count,
        )
        if invalid_count > 0:
            for reason_row in invalid_df.groupBy("rejection_reason").count().collect():
                db.log_quarantine(
                    conn, run_id, SOURCE_NAME, business_date=business_date_end,
                    rejection_reason=reason_row["rejection_reason"], record_count=reason_row["count"],
                    quarantine_file_path=layer_path("quarantine", SOURCE_NAME),
                )
        conn.commit()

    spark.stop()
    return {"status": "SUCCEEDED", "records_read": records_read, "valid": valid_count, "invalid": invalid_count}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business-date-start", type=str, default=None)
    parser.add_argument("--business-date-end", type=str, default=None)
    args = parser.parse_args(argv)

    start = dt.date.fromisoformat(args.business_date_start) if args.business_date_start else None
    end = dt.date.fromisoformat(args.business_date_end) if args.business_date_end else None
    result = run(start, end)
    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()
