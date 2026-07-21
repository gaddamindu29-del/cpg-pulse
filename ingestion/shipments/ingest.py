#!/usr/bin/env python
"""Manufacturer shipments ingestion. See ingestion/retailer_sales/ingest.py
for the full pattern description.

CLI usage:
    python -m ingestion.shipments.ingest
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
    source_name="manufacturer_shipments",
    generated_dir="data/generated/manufacturer_shipments",
    required_columns=[
        "shipment_id", "retailer_id", "distribution_center_id", "product_id",
        "shipment_date", "units_shipped", "shipment_status",
        "estimated_delivery_date",
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
