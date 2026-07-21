"""Query layer for /promotions/performance."""

from __future__ import annotations

from ..db import fetch_all, fetch_scalar, warehouse_engine


def list_promotion_performance(
    page: int, page_size: int, retailer_id: str | None, promotion_type: str | None, min_lift_percentage: float | None,
) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if retailer_id:
        where.append("retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if promotion_type:
        where.append("promotion_type = :promotion_type")
        params["promotion_type"] = promotion_type
    if min_lift_percentage is not None:
        where.append("lift_percentage >= :min_lift_percentage")
        params["min_lift_percentage"] = min_lift_percentage
    where_clause = " AND ".join(where)

    total = fetch_scalar(warehouse_engine(), f"SELECT count(*) FROM marts.mart_promotion_effectiveness WHERE {where_clause}", params)
    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        warehouse_engine(),
        f"""
        SELECT promotion_id, retailer_id, product_id, promotion_type, display_type,
               start_date, end_date, duration_days, regular_price, promotional_price,
               discount_percentage, marketing_spend, baseline_days, baseline_avg_daily_units,
               expected_baseline_units, actual_promo_units, actual_promo_net_sales,
               incremental_units, incremental_revenue, discount_cost, lift_percentage, promotion_roi
        FROM marts.mart_promotion_effectiveness
        WHERE {where_clause}
        ORDER BY lift_percentage DESC NULLS LAST
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total
