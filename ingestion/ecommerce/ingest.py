#!/usr/bin/env python
"""Direct-to-consumer e-commerce order ingestion. See
ingestion/retailer_sales/ingest.py for the full pattern description.

CLI usage:
    python -m ingestion.ecommerce.ingest
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
    source_name="ecommerce_orders",
    generated_dir="data/generated/ecommerce_orders",
    required_columns=[
        "order_id", "order_date", "customer_id", "product_id", "units_ordered",
        "unit_price", "discount_amount", "net_sales", "order_status",
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
