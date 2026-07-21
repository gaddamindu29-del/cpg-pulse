"""Shared ingestion infrastructure used by every per-source ingestion module.

Design: `run_ingestion()` in `base_ingest.py` is a single generic engine
parameterized by a `SourceConfig`. Each source folder (retailer_sales/,
inventory/, shipments/, promotions/, ecommerce/, product_master/) is a thin
wrapper that supplies its own `SourceConfig` and calls the shared engine --
this avoids six near-identical copies of "discover files, check schema, land
raw, update watermark, log run" while still giving each source its own
importable module and CLI entrypoint (what Airflow's per-source DAGs call).
"""
