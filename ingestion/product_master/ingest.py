#!/usr/bin/env python
"""Reference/master data ingestion: product master plus the other small
reference tables that share its pattern (store master, retailer<->product
mapping, calendar, retailers, distribution centers). All are full-snapshot
files landed idempotently via content hash (see
ingestion/common/base_ingest.py's non-partitioned branch) rather than
date-partitioned watermarks, because a master-data extract is republished in
full each time, not appended to.

This corresponds to the "Product-master ingestion" DAG in the 12-DAG list
(docs/architecture.md / airflow/dags/product_master_ingestion_dag.py); it is
bundled with the other reference tables here rather than split into six
near-empty modules, since they are all the same one-shot pattern.

CLI usage:
    python -m ingestion.product_master.ingest
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.common.base_ingest import SourceConfig, run_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

REFERENCE_SOURCES = [
    SourceConfig(
        source_name="product_master",
        generated_dir="data/generated/product_master",
        required_columns=[
            "product_id", "upc", "brand", "category", "subcategory",
            "product_name", "package_size", "case_quantity", "unit_cost", "launch_date",
        ],
        partitioned=False,
    ),
    SourceConfig(
        source_name="store_master",
        generated_dir="data/generated/store_master",
        required_columns=[
            "store_id", "retailer_id", "store_name", "city", "state", "region",
            "store_format", "opening_date",
        ],
        partitioned=False,
    ),
    SourceConfig(
        source_name="retailer_product_mapping",
        generated_dir="data/generated/retailer_product_mapping",
        required_columns=[
            "retailer_id", "retailer_product_id", "product_id", "match_method",
            "match_confidence", "effective_start_date",
        ],
        partitioned=False,
    ),
    SourceConfig(
        source_name="calendar",
        generated_dir="data/generated/calendar",
        required_columns=["date", "week", "month", "quarter", "year", "day_of_week"],
        partitioned=False,
    ),
    SourceConfig(
        source_name="retailers",
        generated_dir="data/generated/retailers",
        required_columns=["retailer_id", "retailer_name", "retailer_type"],
        partitioned=False,
    ),
    SourceConfig(
        source_name="distribution_centers",
        generated_dir="data/generated/distribution_centers",
        required_columns=["distribution_center_id", "dc_name", "region"],
        partitioned=False,
    ),
]


def main(argv=None) -> None:
    logger = logging.getLogger(__name__)
    for cfg in REFERENCE_SOURCES:
        result = run_ingestion(cfg)
        logger.info("Result [%s]: %s", cfg.source_name, result)


if __name__ == "__main__":
    main()
