#!/usr/bin/env python
"""PySpark standardization job for retail POS sales.

Raw layer (byte-exact retailer files, see ingestion/retailer_sales/ingest.py)
-> Standardized layer (canonical schema, canonical product_id, deduplicated,
invalid rows quarantined).

Pipeline:
  1. Read every raw retail_pos_sales file.
  2. Cast to an explicit target schema (never trust inferred dtypes -- see
     spark/transformations/common.py::cast_columns docstring).
  3. Resolve retailer_product_id -> product_id via the SCD2-aware
     retailer_product_mapping join (spark/transformations/canonical_ids.py).
  4. Validate store_id against store_master (open, correct retailer).
  5. Deduplicate on the fact's natural business key.
  6. Split into valid (-> standardized layer) and invalid (-> quarantine,
     with a rejection_reason) using business rules from
     docs/architecture.md section 9 ("Data Quality Strategy").

Usage:
    python spark/jobs/standardize_pos_sales.py
    python spark/jobs/standardize_pos_sales.py --business-date-start 2025-01-01 --business-date-end 2025-01-31
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
logger = logging.getLogger("standardize_pos_sales")

SOURCE_NAME = "retail_pos_sales"
BUSINESS_KEY = ["retailer_id", "store_id", "retailer_product_id", "transaction_date", "sales_channel"]
TARGET_TYPES = {
    "units_sold": "int",
    "gross_sales": "double",
    "discount_amount": "double",
    "net_sales": "double",
    "regular_price": "double",
    "selling_price": "double",
    "transaction_date": "date",
}
VALID_SALES_CHANNELS = ["IN_STORE", "RETAILER_ONLINE", "MARKETPLACE", "DTC_ECOMMERCE"]
MAX_REASONABLE_PRICE = 500.0  # configurable in principle; see docs/metrics.md assumptions


def run(business_date_start: dt.date | None, business_date_end: dt.date | None) -> dict:
    spark = get_spark_session("standardize_pos_sales")
    batch_id = str(uuid.uuid4())

    raw_path = layer_path("raw", SOURCE_NAME)
    raw_df = common.read_raw(spark, raw_path, fmt="csv")
    if raw_df.rdd.isEmpty():
        logger.info("no raw data found at %s -- nothing to standardize", raw_path)
        return {"status": "SKIPPED", "records_read": 0}

    df = common.cast_columns(raw_df, TARGET_TYPES)

    if business_date_start:
        df = df.filter(F.col("transaction_date") >= F.lit(business_date_start.isoformat()))
    if business_date_end:
        df = df.filter(F.col("transaction_date") <= F.lit(business_date_end.isoformat()))

    records_read = df.count()
    df = common.add_lineage_columns(df, batch_id)

    mapping_df = spark.read.option("header", "true").option("inferSchema", "true").csv(
        layer_path("raw", "retailer_product_mapping")
    )
    mapping_df = common.cast_columns(mapping_df, {"effective_start_date": "date", "effective_end_date": "date"})
    store_df = spark.read.option("header", "true").option("inferSchema", "true").csv(layer_path("raw", "store_master"))
    store_df = common.cast_columns(store_df, {"opening_date": "date", "closing_date": "date"})

    df = canonical_ids.resolve_product_id(df, mapping_df, business_date_col="transaction_date")
    df = canonical_ids.validate_store(df, store_df, business_date_col="transaction_date")

    df = common.deduplicate(df, BUSINESS_KEY)

    # Business-rule validation (docs/architecture.md section 9). Order matters
    # for the rejection_reason: first rule matched wins.
    invalid_condition = (
        F.col("product_id").isNull()
        | (~F.col("store_valid"))
        | F.col("units_sold").isNull()
        | (F.col("units_sold") <= 0)
        | F.col("net_sales").isNull()
        | (F.col("net_sales") < 0)
        | (F.col("selling_price") > MAX_REASONABLE_PRICE)
        | (F.col("sales_channel").isNull())
        | (~F.col("sales_channel").isin(VALID_SALES_CHANNELS))
    )

    def reason_expr():
        return (
            F.when(F.col("product_id").isNull(), F.lit("UNRESOLVED_RETAILER_PRODUCT_ID"))
            .when(~F.col("store_valid"), F.lit("INVALID_OR_CLOSED_STORE"))
            .when(F.col("units_sold").isNull() | (F.col("units_sold") <= 0), F.lit("NON_POSITIVE_UNITS_SOLD"))
            .when(F.col("net_sales").isNull() | (F.col("net_sales") < 0), F.lit("NEGATIVE_OR_NULL_NET_SALES"))
            .when(F.col("selling_price") > MAX_REASONABLE_PRICE, F.lit("SELLING_PRICE_EXCEEDS_THRESHOLD"))
            .when(F.col("sales_channel").isNull() | (~F.col("sales_channel").isin(VALID_SALES_CHANNELS)), F.lit("INVALID_SALES_CHANNEL"))
            .otherwise(F.lit("UNKNOWN"))
        )

    invalid_df = df.filter(invalid_condition).withColumn("rejection_reason", reason_expr())
    valid_df = df.filter(~invalid_condition).drop("store_valid")

    valid_count = valid_df.count()
    invalid_count = invalid_df.count()

    common.write_standardized(valid_df, layer_path("standardized", SOURCE_NAME), partition_col="transaction_date")
    common.write_quarantine(invalid_df, layer_path("quarantine", SOURCE_NAME), partition_col="transaction_date")

    logger.info(
        "standardize_pos_sales: read=%d valid=%d invalid=%d (batch_id=%s)",
        records_read, valid_count, invalid_count, batch_id,
    )

    with db.connection_scope() as conn:
        run_id = db.start_run(
            conn, dag_id="pyspark_standardization", task_id="standardize_pos_sales",
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
