"""Canonical ID resolution: mapping retailer-specific identifiers onto
CPG Pulse's internal product/store/retailer identifier space
(docs/architecture.md "Standardized Layer"). This is the single most
important transformation in the whole platform -- everything downstream
(warehouse facts, stockout risk, promotion lift, reconciliation) depends on
every retailer's data landing on the same `product_id`/`store_id` keys.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def resolve_product_id(sales_df: DataFrame, mapping_df: DataFrame, business_date_col: str) -> DataFrame:
    """Join on (retailer_id, retailer_product_id), keeping only the mapping
    row whose effective date range covers each transaction's business date --
    this is what makes the join SCD2-aware: a retailer_product_id that was
    remapped to a different product_id mid-history resolves correctly on
    both sides of the remap date, rather than picking one arbitrarily.
    """
    mapping_effective = mapping_df.select(
        F.col("retailer_id").alias("_map_retailer_id"),
        F.col("retailer_product_id").alias("_map_retailer_product_id"),
        F.col("product_id"),
        F.col("effective_start_date"),
        F.col("effective_end_date"),
        F.col("match_confidence"),
        F.col("match_method"),
    )

    joined = sales_df.join(
        mapping_effective,
        (sales_df["retailer_id"] == mapping_effective["_map_retailer_id"])
        & (sales_df["retailer_product_id"] == mapping_effective["_map_retailer_product_id"])
        & (sales_df[business_date_col] >= mapping_effective["effective_start_date"])
        & (
            mapping_effective["effective_end_date"].isNull()
            | (sales_df[business_date_col] <= mapping_effective["effective_end_date"])
        ),
        how="left",
    ).drop("_map_retailer_id", "_map_retailer_product_id", "effective_start_date", "effective_end_date")

    return joined


def validate_store(df: DataFrame, store_df: DataFrame, business_date_col: str) -> DataFrame:
    """Left-join to store_master and add a `store_valid` flag: the store must
    exist for that retailer and must have been open (and not yet closed) as
    of the business date.
    """
    stores = store_df.select(
        F.col("store_id").alias("_store_store_id"),
        F.col("retailer_id").alias("_store_retailer_id"),
        F.col("opening_date"),
        F.col("closing_date"),
        F.col("region"),
        F.col("store_format"),
    )
    joined = df.join(
        stores,
        (df["store_id"] == stores["_store_store_id"]) & (df["retailer_id"] == stores["_store_retailer_id"]),
        how="left",
    )
    joined = joined.withColumn(
        "store_valid",
        stores["_store_store_id"].isNotNull()
        & (F.col(business_date_col) >= F.col("opening_date"))
        & (F.col("closing_date").isNull() | (F.col(business_date_col) <= F.col("closing_date"))),
    )
    return joined.drop("_store_store_id", "_store_retailer_id")
