"""Promotion calendar generation.

Promotions are generated per (retailer_id, product_id) pair that is actively
carried (per the retailer-product mapping), a handful of promo windows spread
across the data window. `simulate.py` looks up this calendar to apply a demand
lift and price change on promoted days, so the promotion data and the sales
data are internally consistent (a real promotion effectiveness analysis
depends on that consistency).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import DISPLAY_TYPES, PROMOTION_TYPES, GeneratorConfig


def build_promotions(cfg: GeneratorConfig, mapping: pd.DataFrame, price_table: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("promotions")
    pairs = mapping[["retailer_id", "product_id"]].drop_duplicates().merge(
        price_table, on=["retailer_id", "product_id"], how="left"
    )
    total_days = (cfg.end_date - cfg.start_date).days + 1

    rows = []
    promo_seq = 1
    for _, pair in pairs.iterrows():
        n_promos = int(rng.integers(2, 6))  # 2-5 promo windows per pair over the window
        used_ranges: list[tuple[int, int]] = []
        attempts = 0
        placed = 0
        while placed < n_promos and attempts < n_promos * 6:
            attempts += 1
            duration = int(rng.choice([7, 14, 21, 28], p=[0.35, 0.35, 0.2, 0.1]))
            start_offset = int(rng.integers(0, max(1, total_days - duration)))
            end_offset = start_offset + duration - 1
            if any(not (end_offset < s or start_offset > e) for s, e in used_ranges):
                continue  # overlaps an existing promo for this pair, retry
            used_ranges.append((start_offset, end_offset))
            placed += 1

            start_date = cfg.start_date + dt.timedelta(days=start_offset)
            end_date = cfg.start_date + dt.timedelta(days=end_offset)
            regular_price = float(pair["regular_price"])
            discount_pct = round(float(rng.choice([10, 15, 20, 25, 30], p=[0.25, 0.3, 0.25, 0.15, 0.05])), 1)
            promotional_price = round(regular_price * (1 - discount_pct / 100), 2)
            promo_type = rng.choice(PROMOTION_TYPES)
            display_type = rng.choice(DISPLAY_TYPES, p=[0.2, 0.2, 0.2, 0.2, 0.2])
            marketing_spend = round(float(rng.uniform(200, 4000)) * (duration / 14), 2)

            # Ground-truth demand lift used only internally by simulate.py to make
            # POS sales consistent with the promotion calendar. This is exactly
            # what promotion-effectiveness analytics in later phases must
            # *estimate* from observed data -- it is intentionally not written to
            # the public promotions.csv/json/parquet output (see writers usage in
            # generate_synthetic_data.py, which selects only the public columns).
            true_lift_factor = round(float(rng.uniform(1.4, 2.8)), 3)

            rows.append(
                {
                    "promotion_id": f"PROMO-{promo_seq:06d}",
                    "retailer_id": pair["retailer_id"],
                    "product_id": pair["product_id"],
                    "promotion_type": promo_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "regular_price": regular_price,
                    "promotional_price": promotional_price,
                    "discount_percentage": discount_pct,
                    "display_type": display_type,
                    "marketing_spend": marketing_spend,
                    "true_lift_factor_internal": true_lift_factor,
                }
            )
            promo_seq += 1

    return pd.DataFrame(rows)


PUBLIC_PROMOTION_COLUMNS = [
    "promotion_id", "retailer_id", "product_id", "promotion_type", "start_date",
    "end_date", "regular_price", "promotional_price", "discount_percentage",
    "display_type", "marketing_spend",
]


def promo_lookup_index(promotions: pd.DataFrame) -> dict[tuple[str, str], list[tuple[dt.date, dt.date, float, float]]]:
    """(retailer_id, product_id) -> list of (start_date, end_date, promotional_price, true_lift_factor).

    Used by simulate.py for fast day-by-day promo-active lookups without a
    per-day dataframe join.
    """
    idx: dict[tuple[str, str], list[tuple[dt.date, dt.date, float, float]]] = {}
    for row in promotions.itertuples(index=False):
        key = (row.retailer_id, row.product_id)
        idx.setdefault(key, []).append(
            (row.start_date, row.end_date, row.promotional_price, row.true_lift_factor_internal)
        )
    return idx
