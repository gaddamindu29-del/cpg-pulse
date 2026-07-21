#!/usr/bin/env python
"""Retail inventory ingestion. See ingestion/retailer_sales/ingest.py for the
full pattern description -- this module only supplies the source-specific
config. Note `reserved_units` is intentionally NOT in `required_columns`:
pre-schema-change files call it `reserved_qty` (see
scripts/data_gen/quality_issues.py), and that rename is exactly the kind of
"breaking" schema change ingestion is meant to *detect and log*, not reject
raw files over -- see ingestion/common/base_ingest.py's module docstring.

CLI usage:
    python -m ingestion.inventory.ingest
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
    source_name="retail_inventory",
    generated_dir="data/generated/retail_inventory",
    required_columns=[
        "retailer_id", "store_id", "retailer_product_id", "snapshot_date",
        "on_hand_units", "on_order_units", "available_units",
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
