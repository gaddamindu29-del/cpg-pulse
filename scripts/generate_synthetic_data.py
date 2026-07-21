#!/usr/bin/env python
"""Generate the full CPG Pulse synthetic dataset.

Produces all 9 source datasets described in docs/architecture.md under
`data/generated/`, in CSV, JSON, and Parquet, with realistic cross-references,
seasonality, promotions, and deliberately injected data-quality problems
(duplicates, nulls, invalid foreign keys, late-arriving records, and a schema
change partway through the window).

Usage:
    python scripts/generate_synthetic_data.py
    python scripts/generate_synthetic_data.py --seed 7 --num-products 150 \\
        --start-date 2025-01-01 --end-date 2025-12-31 --formats csv,parquet

Reproducibility: the entire run is driven by a single `--seed`. The same seed
always produces byte-identical output (see tests/unit/test_generator.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_gen import ecommerce, pricing, promotions as promo_mod, quality_issues, reference, simulate, writers
from data_gen.config import GeneratorConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("generate_synthetic_data")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=42, help="Master random seed (default: 42)")
    p.add_argument("--start-date", type=str, default="2025-01-01", help="Inclusive start date, YYYY-MM-DD")
    p.add_argument("--end-date", type=str, default="2026-06-30", help="Inclusive end date, YYYY-MM-DD")
    p.add_argument("--num-products", type=int, default=110, help="Number of SKUs in the product master")
    p.add_argument(
        "--stores-per-retailer",
        type=str,
        default="RTL-WMT=40,RTL-TGT=30,RTL-KRG=25,RTL-AMZ=6",
        help="Comma-separated retailer_id=store_count pairs",
    )
    p.add_argument("--output-dir", type=str, default="data/generated", help="Root output directory")
    p.add_argument("--formats", type=str, default="csv,json,parquet", help="Comma-separated output formats")
    return p.parse_args(argv)


def _parse_stores_per_retailer(raw: str) -> dict[str, int]:
    result = {}
    for chunk in raw.split(","):
        retailer_id, count = chunk.split("=")
        result[retailer_id.strip()] = int(count.strip())
    return result


def build_config(args: argparse.Namespace) -> GeneratorConfig:
    return GeneratorConfig(
        seed=args.seed,
        start_date=dt.date.fromisoformat(args.start_date),
        end_date=dt.date.fromisoformat(args.end_date),
        num_products=args.num_products,
        stores_per_retailer=_parse_stores_per_retailer(args.stores_per_retailer),
        output_dir=args.output_dir,
    )


def run(cfg: GeneratorConfig, formats: tuple[str, ...]) -> dict[str, int]:
    t0 = time.time()
    row_counts: dict[str, int] = {}

    logger.info("Building reference data (retailers, DCs, products, stores, mapping, calendar)...")
    retailers = reference.build_retailers()
    distribution_centers = reference.build_distribution_centers()
    products = reference.build_product_master(cfg)
    stores = reference.build_store_master(cfg)
    mapping = reference.build_retailer_product_mapping(cfg, products, retailers)
    calendar = reference.build_calendar(cfg)
    price_table = pricing.build_regular_price_table(cfg, mapping, products)

    logger.info("Building promotion calendar...")
    promotions = promo_mod.build_promotions(cfg, mapping, price_table)

    logger.info(
        "Simulating POS sales, inventory, and shipments for %d products x %d stores "
        "(this is the slow step; expect ~10-60s depending on volume)...",
        len(products), len(stores),
    )
    sim = simulate.simulate_transactions(cfg, retailers, stores, products, mapping, price_table, promotions)
    pos_sales, inventory_snapshots, shipments = sim["pos_sales"], sim["inventory_snapshots"], sim["shipments"]

    logger.info("Simulating direct-to-consumer e-commerce orders...")
    ecommerce_orders = ecommerce.build_ecommerce_orders(cfg, products)

    logger.info("Injecting data-quality issues (duplicates, nulls, invalid FKs, late arrivals, outliers)...")
    pos_sales = quality_issues.inject_pos_issues(cfg, pos_sales, mapping)
    inventory_snapshots = quality_issues.inject_inventory_issues(cfg, inventory_snapshots)
    shipments = quality_issues.inject_shipment_issues(cfg, shipments)
    ecommerce_orders = quality_issues.inject_ecommerce_issues(cfg, ecommerce_orders)

    pos_pre, pos_post = quality_issues.apply_pos_schema_evolution(cfg, pos_sales)
    inv_pre, inv_post = quality_issues.apply_inventory_schema_evolution(cfg, inventory_snapshots)

    logger.info("Writing output files to %s (formats=%s)...", cfg.output_dir, formats)

    writers.write_reference_dataset(retailers, "retailers", cfg.output_dir, formats)
    writers.write_reference_dataset(distribution_centers, "distribution_centers", cfg.output_dir, formats)
    writers.write_reference_dataset(products, "product_master", cfg.output_dir, formats)
    writers.write_reference_dataset(stores, "store_master", cfg.output_dir, formats)
    writers.write_reference_dataset(mapping, "retailer_product_mapping", cfg.output_dir, formats)
    writers.write_reference_dataset(calendar, "calendar", cfg.output_dir, formats)
    writers.write_reference_dataset(
        promotions[promo_mod.PUBLIC_PROMOTION_COLUMNS], "promotions", cfg.output_dir, formats
    )

    writers.write_partitioned_dataset(pos_pre, "retail_pos_sales", cfg.output_dir, formats, file_suffix="_a")
    writers.write_partitioned_dataset(pos_post, "retail_pos_sales", cfg.output_dir, formats, file_suffix="_b")
    writers.write_partitioned_dataset(inv_pre, "retail_inventory", cfg.output_dir, formats, file_suffix="_a")
    writers.write_partitioned_dataset(inv_post, "retail_inventory", cfg.output_dir, formats, file_suffix="_b")
    writers.write_partitioned_dataset(shipments, "manufacturer_shipments", cfg.output_dir, formats)
    writers.write_partitioned_dataset(ecommerce_orders, "ecommerce_orders", cfg.output_dir, formats)

    row_counts = {
        "retailers": len(retailers),
        "distribution_centers": len(distribution_centers),
        "product_master": len(products),
        "store_master": len(stores),
        "retailer_product_mapping": len(mapping),
        "calendar": len(calendar),
        "promotions": len(promotions),
        "retail_pos_sales": len(pos_sales),
        "retail_inventory": len(inventory_snapshots),
        "manufacturer_shipments": len(shipments),
        "ecommerce_orders": len(ecommerce_orders),
    }

    elapsed = time.time() - t0
    logger.info("Done in %.1fs. Row counts: %s", elapsed, row_counts)
    return row_counts


def main(argv=None) -> None:
    args = parse_args(argv)
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    cfg = build_config(args)
    logger.info(
        "Config: seed=%d, dates=%s..%s, num_products=%d, stores_per_retailer=%s",
        cfg.seed, cfg.start_date, cfg.end_date, cfg.num_products, cfg.stores_per_retailer,
    )
    run(cfg, formats)


if __name__ == "__main__":
    main()
