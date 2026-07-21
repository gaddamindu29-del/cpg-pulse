"""Synthetic data generation package for CPG Pulse.

Submodules are organized by concern so `generate_synthetic_data.py` stays a thin
orchestrator:

- config: run configuration, seeded RNGs, and reference vocabularies (brands,
  categories, regions, ...)
- reference: master/dimension-style data (products, stores, retailers,
  distribution centers, retailer<->product mapping, calendar)
- promotions: promotion calendar generation
- simulate: the core per (retailer, store, product) demand/inventory/shipment
  time-series simulation
- ecommerce: direct-to-consumer order generation
- quality_issues: deliberate data-quality problem injection (duplicates, nulls,
  invalid FKs, late arrivals, schema drift, price outliers)
- writers: multi-format (CSV/JSON/Parquet) output helpers
"""
