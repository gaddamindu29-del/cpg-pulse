"""Query layer for /products and /products/{product_id}/performance.
Reads exclusively from marts.dim_product and marts.mart_product_scorecard --
no business logic here beyond building the SQL, which stays in dbt (see
docs/architecture.md's exposures in dbt/models/marts/_exposures.yml).
"""

from __future__ import annotations

from ..db import fetch_all, fetch_one, fetch_scalar, warehouse_engine


def list_products(page: int, page_size: int, category: str | None, brand: str | None, include_discontinued: bool) -> tuple[list[dict], int]:
    where = ["is_current = true"]
    params: dict = {}
    if category:
        where.append("category = :category")
        params["category"] = category
    if brand:
        where.append("brand = :brand")
        params["brand"] = brand
    if not include_discontinued:
        where.append("is_discontinued = false")
    where_clause = " AND ".join(where)

    total = fetch_scalar(warehouse_engine(), f"SELECT count(*) FROM marts.dim_product WHERE {where_clause}", params)

    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        warehouse_engine(),
        f"""
        SELECT product_id, upc, brand, category, subcategory, product_name, flavor,
               package_size, case_quantity, unit_cost, launch_date, discontinued_date, is_discontinued
        FROM marts.dim_product
        WHERE {where_clause}
        ORDER BY product_id
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total


def get_product_performance(product_id: str) -> dict | None:
    return fetch_one(
        warehouse_engine(),
        """
        SELECT product_id, brand, category, subcategory, unit_cost, is_discontinued,
               total_units_sold_all_channels, total_net_sales_all_channels,
               distinct_retailers_carrying, distinct_stores_selling,
               first_sale_date, last_sale_date,
               high_stockout_risk_snapshots, total_inventory_snapshots, high_stockout_risk_rate,
               excess_inventory_snapshots, promotion_count
        FROM marts.mart_product_scorecard
        WHERE product_id = :product_id
        """,
        {"product_id": product_id},
    )
