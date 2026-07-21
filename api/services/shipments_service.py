"""Query layer for /shipments/reconciliation."""

from __future__ import annotations

import datetime as dt

from ..db import fetch_all, fetch_scalar, warehouse_engine


def list_reconciliation(
    page: int, page_size: int, retailer_id: str | None, signal: str | None, since: dt.date | None,
) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if retailer_id:
        where.append("retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if signal:
        where.append("reconciliation_signal = :signal")
        params["signal"] = signal
    if since:
        where.append("week_start >= :since")
        params["since"] = since
    where_clause = " AND ".join(where)

    total = fetch_scalar(warehouse_engine(), f"SELECT count(*) FROM marts.mart_shipment_pos_reconciliation WHERE {where_clause}", params)
    params_paged = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = fetch_all(
        warehouse_engine(),
        f"""
        SELECT retailer_id, product_id, week_start, units_shipped, units_sold,
               variance_units, variance_pct, reconciliation_signal
        FROM marts.mart_shipment_pos_reconciliation
        WHERE {where_clause}
        ORDER BY week_start DESC
        LIMIT :limit OFFSET :offset
        """,
        params_paged,
    )
    return rows, total
