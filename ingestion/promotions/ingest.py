#!/usr/bin/env python
"""Promotion calendar ingestion. Promotions are generated as a single
reference-style snapshot (not partitioned by extract_date -- a promotion
calendar is typically republished in full each time trade marketing updates
it, not appended to incrementally), so this uses content-hash-based
idempotent landing rather than a date watermark.

CLI usage:
    python -m ingestion.promotions.ingest
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.common.base_ingest import SourceConfig, run_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SOURCE_CONFIG = SourceConfig(
    source_name="promotions",
    generated_dir="data/generated/promotions",
    required_columns=[
        "promotion_id", "retailer_id", "product_id", "promotion_type",
        "start_date", "end_date", "regular_price", "promotional_price",
        "discount_percentage",
    ],
    partitioned=False,
    preferred_format="csv",
)


def main(argv=None) -> None:
    result = run_ingestion(SOURCE_CONFIG)
    logging.getLogger(__name__).info("Result: %s", result)


if __name__ == "__main__":
    main()
