"""Query layer for /retailers/{retailer_id}/performance."""

from __future__ import annotations

from ..db import fetch_one, warehouse_engine


def get_retailer_performance(retailer_id: str) -> dict | None:
    return fetch_one(
        warehouse_engine(),
        """
        SELECT retailer_id, retailer_name, retailer_type, total_units_sold, total_gross_sales,
               total_net_sales, net_to_gross_ratio, distinct_products_sold, distinct_stores,
               first_sale_date, last_sale_date, high_stockout_risk_snapshots,
               total_inventory_snapshots, high_stockout_risk_rate, excess_inventory_snapshots,
               promotion_count, total_marketing_spend
        FROM marts.mart_retailer_scorecard
        WHERE retailer_id = :retailer_id
        """,
        {"retailer_id": retailer_id},
    )
