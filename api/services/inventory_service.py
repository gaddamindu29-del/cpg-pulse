"""Query layer for /inventory/stockout-risk and /inventory/excess-risk.

Both default to the *latest available snapshot_date per (retailer, store,
product)* rather than every historical snapshot -- callers almost always
want "who's at risk right now," not the full history (which is still
queryable via `as_of_date`).
"""

from __future__ import annotations

import datetime as dt

from ..db import fetch_all, fetch_scalar, warehouse_engine


def _latest_snapshot_date(table: str) -> dt.date | None:
    return fetch_scalar(warehouse_engine(), f"SELECT max(snapshot_date) FROM marts.{table}")


def list_stockout_risk(
    page: int, page_size: int, retailer_id: str | None, store_id: str | None,
    risk_level: str | None, as_of_date: dt.date | None,
) -> tuple[list[dict], int]:
    snapshot_date = as_of_date or _latest_snapshot_date("mart_stockout_risk")
    where = ["r.snapshot_date = :snapshot_date"]
    params: dict = {"snapshot_date": snapshot_date}
    if retailer_id:
        where.append("r.retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if store_id:
        where.append("r.store_id = :store_id")
        params["store_id"] = store_id
    if risk_level:
        where.append("r.stockout_risk_level = :risk_level")
        params["risk_level"] = risk_level
    where_clause = " AND ".join(where)

    total = fetch_scalar(warehouse_engine(), f"SELECT count(*) FROM marts.mart_stockout_risk r WHERE {where_clause}", params)
    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        warehouse_engine(),
        f"""
        SELECT r.retailer_id, r.store_id, r.product_id, r.snapshot_date, r.on_hand_units,
               r.available_units, r.avg_daily_units_sold, r.velocity_trend, r.days_of_supply,
               r.stockout_risk_level
        FROM marts.mart_stockout_risk r
        WHERE {where_clause}
        ORDER BY r.days_of_supply ASC NULLS LAST
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total


def list_excess_risk(
    page: int, page_size: int, retailer_id: str | None, store_id: str | None,
    risk_level: str | None, as_of_date: dt.date | None,
) -> tuple[list[dict], int]:
    snapshot_date = as_of_date or _latest_snapshot_date("mart_excess_inventory_risk")
    where = ["r.snapshot_date = :snapshot_date"]
    params: dict = {"snapshot_date": snapshot_date}
    if retailer_id:
        where.append("r.retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if store_id:
        where.append("r.store_id = :store_id")
        params["store_id"] = store_id
    if risk_level:
        where.append("r.excess_inventory_risk_level = :risk_level")
        params["risk_level"] = risk_level
    where_clause = " AND ".join(where)

    total = fetch_scalar(warehouse_engine(), f"SELECT count(*) FROM marts.mart_excess_inventory_risk r WHERE {where_clause}", params)
    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        warehouse_engine(),
        f"""
        SELECT r.retailer_id, r.store_id, r.product_id, r.snapshot_date, r.on_hand_units,
               r.available_units, r.avg_daily_units_sold, r.velocity_trend, r.days_of_supply,
               r.is_excess_inventory, r.excess_inventory_risk_level
        FROM marts.mart_excess_inventory_risk r
        WHERE {where_clause}
        ORDER BY r.days_of_supply DESC NULLS LAST
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total
