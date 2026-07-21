"""Shared retailer-product pricing so promotions, POS sales, and inventory all
reference the same "regular price" for a given (retailer_id, product_id) pair
instead of each module inventing its own number.
"""

from __future__ import annotations

import pandas as pd

from .config import GeneratorConfig


def build_regular_price_table(cfg: GeneratorConfig, mapping: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """One row per (retailer_id, product_id) with a stable regular_price.

    Retail markup varies a bit by retailer banner (mass merchandisers price
    slightly lower than grocery/marketplace) to make retailer-level price
    comparisons meaningful.
    """
    rng = cfg.rng("pricing")
    markup_by_retailer = {"RTL-WMT": 1.55, "RTL-TGT": 1.65, "RTL-KRG": 1.80, "RTL-AMZ": 1.70}

    pairs = mapping[["retailer_id", "product_id"]].drop_duplicates()
    merged = pairs.merge(products[["product_id", "unit_cost"]], on="product_id", how="left")

    def price_row(r):
        markup = markup_by_retailer.get(r["retailer_id"], 1.65)
        noise = rng.uniform(0.95, 1.08)
        raw_price = r["unit_cost"] * markup * noise
        return round(max(0.99, raw_price) - 0.01, 2)  # .99-ending psychological pricing

    merged["regular_price"] = merged.apply(price_row, axis=1)
    return merged[["retailer_id", "product_id", "regular_price"]]
