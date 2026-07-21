"""Deliberate data-quality problem injection.

`simulate.py` and `ecommerce.py` produce internally-consistent, "clean" data.
This module takes that clean data and reintroduces the kinds of problems a
real ingestion pipeline has to deal with, so Phase 4 (ingestion/standardization)
has real work to do:

- duplicate records (retailer re-sends a file, or a POS system double-posts)
- missing values in optional-but-expected fields
- invalid foreign keys (retailer references a product ID we don't recognize)
- late-arriving records (business date is much earlier than the file's
  extract/ingestion date)
- price outliers (fat-fingered price entry)

Every injected-issue function adds an `_extract_date` column: the date the
*file containing this row* would have been dropped by the source system. This
is what `writers.py` partitions raw output by, and it is what makes "late
arriving" concrete -- for most rows `_extract_date` is one day after the
business date (the file landed "the next morning"), but for a deliberately
chosen subset it is many days later.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import GeneratorConfig


def _extract_date_column(cfg: GeneratorConfig, business_dates: pd.Series, late_rate: float, rng: np.random.Generator) -> pd.Series:
    n = len(business_dates)
    normal_lag = rng.integers(1, 3, size=n)  # files land 1-2 days after the business date
    late_lag = rng.integers(5, 21, size=n)  # late arrivals: 5-20 days after
    is_late = rng.random(n) < late_rate
    lag_days = np.where(is_late, late_lag, normal_lag)
    return pd.Series(
        [bd + dt.timedelta(days=int(lag)) for bd, lag in zip(business_dates, lag_days)],
        index=business_dates.index,
    )


def inject_pos_issues(cfg: GeneratorConfig, pos_sales: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("dq_pos")
    rates = cfg.dq_issue_rates
    df = pos_sales.copy()

    df["_extract_date"] = _extract_date_column(cfg, df["transaction_date"], rates["pos_late_arrival_rate"], rng)

    # invalid retailer_product_id: reference a SKU the mapping table doesn't know
    invalid_mask = rng.random(len(df)) < rates["pos_invalid_retailer_product_rate"]
    bogus_ids = [f"UNKNOWN-{i}" for i in rng.integers(100000, 999999, size=invalid_mask.sum())]
    df.loc[invalid_mask, "retailer_product_id"] = bogus_ids

    # nulls in optional-looking fields
    null_mask = rng.random(len(df)) < rates["pos_null_field_rate"]
    null_field_choice = rng.integers(0, 2, size=len(df))
    df.loc[null_mask & (null_field_choice == 0), "discount_amount"] = np.nan
    df.loc[null_mask & (null_field_choice == 1), "sales_channel"] = None

    # price outliers (data entry errors)
    outlier_mask = rng.random(len(df)) < rates["price_outlier_rate"]
    df.loc[outlier_mask, "selling_price"] = df.loc[outlier_mask, "selling_price"] * rng.choice([10, 50, 100], size=outlier_mask.sum())

    # duplicates: sample rows and append exact copies (simulates a resend/double-post)
    dup_sample = df.sample(frac=rates["pos_duplicate_rate"], random_state=int(rng.integers(0, 2**31 - 1)))
    df = pd.concat([df, dup_sample], ignore_index=True)

    return df


def inject_inventory_issues(cfg: GeneratorConfig, inventory: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("dq_inventory")
    rates = cfg.dq_issue_rates
    df = inventory.copy()

    df["_extract_date"] = _extract_date_column(cfg, df["snapshot_date"], rates["pos_late_arrival_rate"] / 2, rng)

    null_mask = rng.random(len(df)) < rates["inventory_null_field_rate"]
    df.loc[null_mask, "on_order_units"] = np.nan

    dup_sample = df.sample(frac=rates["inventory_duplicate_rate"], random_state=int(rng.integers(0, 2**31 - 1)))
    df = pd.concat([df, dup_sample], ignore_index=True)

    return df


def inject_shipment_issues(cfg: GeneratorConfig, shipments: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("dq_shipments")
    rates = cfg.dq_issue_rates
    df = shipments.copy()

    df["_extract_date"] = _extract_date_column(cfg, df["shipment_date"], rates["pos_late_arrival_rate"] / 2, rng)

    extra_missing = rng.random(len(df)) < rates["shipment_missing_delivery_rate"]
    df.loc[extra_missing, "actual_delivery_date"] = None

    return df


def inject_ecommerce_issues(cfg: GeneratorConfig, orders: pd.DataFrame) -> pd.DataFrame:
    rng = cfg.rng("dq_ecommerce")
    rates = cfg.dq_issue_rates
    df = orders.copy()

    df["_extract_date"] = _extract_date_column(cfg, df["order_date"], rates["pos_late_arrival_rate"] / 2, rng)

    null_mask = rng.random(len(df)) < rates["ecommerce_null_field_rate"]
    df.loc[null_mask, "fulfillment_type"] = None

    dup_sample = df.sample(frac=rates["ecommerce_duplicate_rate"], random_state=int(rng.integers(0, 2**31 - 1)))
    df = pd.concat([df, dup_sample], ignore_index=True)

    return df


def apply_inventory_schema_evolution(cfg: GeneratorConfig, inventory_with_issues: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split inventory into a pre-schema-change and post-schema-change frame that
    use *different column names* for the same concept, mimicking a retailer
    renaming a field in its feed (`reserved_qty` -> `reserved_units`) partway
    through the data history. This is a **breaking** change: consumers keyed on
    the old column name will fail unless ingestion maps both.

    Returns (pre_change_df, post_change_df); writers.py writes them as separate
    file generations so the rename is visible in the raw layer, exactly as a
    real retailer feed change would look.
    """
    pre = inventory_with_issues[inventory_with_issues["snapshot_date"] < cfg.schema_change_date].copy()
    post = inventory_with_issues[inventory_with_issues["snapshot_date"] >= cfg.schema_change_date].copy()
    pre = pre.rename(columns={"reserved_units": "reserved_qty"})
    return pre, post


def apply_pos_schema_evolution(cfg: GeneratorConfig, pos_with_issues: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compatible schema change: on/after `schema_change_date`, POS files for
    RTL-WMT gain a new optional `promo_flag` column. Rows/files before that
    date simply don't have the column -- a *compatible* addition, unlike the
    inventory rename above.
    """
    pre = pos_with_issues[pos_with_issues["transaction_date"] < cfg.schema_change_date].copy()
    post = pos_with_issues[pos_with_issues["transaction_date"] >= cfg.schema_change_date].copy()
    post = post.copy()
    post["promo_flag"] = post["selling_price"] < post["regular_price"]
    return pre, post
