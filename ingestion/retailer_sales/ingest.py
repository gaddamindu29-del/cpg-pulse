#!/usr/bin/env python
"""Retail POS sales ingestion -- lands new `retail_pos_sales` extract_date
batches from `data/generated/retail_pos_sales/` into the raw lake layer.

CLI usage:
    python -m ingestion.retailer_sales.ingest
    python -m ingestion.retailer_sales.ingest --backfill-start 2025-01-01 --backfill-end 2025-01-31

Called by the `retail_sales_ingestion` Airflow DAG (airflow/dags/retail_sales_ingestion_dag.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.common.base_ingest import SourceConfig, run_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SOURCE_CONFIG = SourceConfig(
    source_name="retail_pos_sales",
    generated_dir="data/generated/retail_pos_sales",
    required_columns=[
        "retailer_id", "store_id", "retailer_product_id", "transaction_date",
        "units_sold", "gross_sales", "discount_amount", "net_sales",
        "regular_price", "selling_price", "sales_channel",
    ],
    partitioned=True,
    preferred_format="csv",
)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill-start", type=str, default=None)
    parser.add_argument("--backfill-end", type=str, default=None)
    args = parser.parse_args(argv)

    backfill_range = None
    if args.backfill_start and args.backfill_end:
        backfill_range = (dt.date.fromisoformat(args.backfill_start), dt.date.fromisoformat(args.backfill_end))

    result = run_ingestion(SOURCE_CONFIG, backfill_range=backfill_range)
    logging.getLogger(__name__).info("Result: %s", result)


if __name__ == "__main__":
    main()
