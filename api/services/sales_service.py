"""Query layer for /sales/summary.

`group_by` is a validated Pydantic enum (api/models/sales.py::SalesGroupBy),
never a raw client-supplied string -- the SQL fragments below are selected
from a fixed dict keyed on that enum, so there is no SQL-injection surface
even though the grouping column itself varies per request.
"""

from __future__ import annotations

import datetime as dt

from ..db import fetch_all, warehouse_engine

_GROUP_BY_SQL = {
    "retailer": {
        "select": "fs.retailer_id AS group_key, r.retailer_name AS group_label",
        "join": "LEFT JOIN marts.dim_retailer r ON fs.retailer_id = r.retailer_id",
        "group": "fs.retailer_id, r.retailer_name",
    },
    "product": {
        "select": "fs.product_id AS group_key, p.product_name AS group_label",
        "join": "LEFT JOIN marts.dim_product p ON fs.product_id = p.product_id AND p.is_current",
        "group": "fs.product_id, p.product_name",
    },
    "category": {
        "select": "p.category AS group_key, p.category AS group_label",
        "join": "LEFT JOIN marts.dim_product p ON fs.product_id = p.product_id AND p.is_current",
        "group": "p.category",
    },
    "brand": {
        "select": "p.brand AS group_key, p.brand AS group_label",
        "join": "LEFT JOIN marts.dim_product p ON fs.product_id = p.product_id AND p.is_current",
        "group": "p.brand",
    },
    "channel": {
        "select": "fs.sales_channel AS group_key, ch.channel_name AS group_label",
        "join": "LEFT JOIN marts.dim_sales_channel ch ON fs.channel_sk = ch.channel_sk",
        "group": "fs.sales_channel, ch.channel_name",
    },
}


def sales_summary(
    group_by: str,
    start_date: dt.date | None,
    end_date: dt.date | None,
    retailer_id: str | None,
    category: str | None,
) -> list[dict]:
    spec = _GROUP_BY_SQL[group_by]

    where = ["1=1"]
    params: dict = {}
    if start_date:
        where.append("fs.transaction_date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where.append("fs.transaction_date <= :end_date")
        params["end_date"] = end_date
    if retailer_id:
        where.append("fs.retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if category:
        where.append("p.category = :category")
        params["category"] = category
        if "dim_product p" not in spec["join"]:
            spec = {**spec, "join": spec["join"] + " LEFT JOIN marts.dim_product p ON fs.product_id = p.product_id AND p.is_current"}

    sql = f"""
        SELECT
            {spec['select']},
            sum(fs.units_sold) AS units_sold,
            sum(fs.gross_sales) AS gross_sales,
            sum(fs.net_sales) AS net_sales,
            round(avg(fs.selling_price), 2) AS avg_selling_price,
            round(sum(fs.discount_amount) / nullif(sum(fs.gross_sales), 0), 4) AS discount_rate
        FROM marts.fact_retail_sales fs
        {spec['join']}
        WHERE {' AND '.join(where)}
        GROUP BY {spec['group']}
        ORDER BY net_sales DESC
    """
    return fetch_all(warehouse_engine(), sql, params)


def omnichannel_performance(start_date: dt.date | None, end_date: dt.date | None) -> list[dict]:
    where = ["1=1"]
    params: dict = {}
    if start_date:
        where.append("sale_date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where.append("sale_date <= :end_date")
        params["end_date"] = end_date

    return fetch_all(
        warehouse_engine(),
        f"""
        SELECT channel_type, sale_date, month_start, units_sold, net_sales,
               distinct_products_sold, distinct_retailers
        FROM marts.mart_omnichannel_performance
        WHERE {' AND '.join(where)}
        ORDER BY sale_date
        """,
        params,
    )
