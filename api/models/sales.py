from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import BaseModel


class SalesGroupBy(str, Enum):
    retailer = "retailer"
    product = "product"
    category = "category"
    brand = "brand"
    channel = "channel"


class SalesSummaryRow(BaseModel):
    group_key: str
    group_label: str
    units_sold: int
    gross_sales: float
    net_sales: float
    avg_selling_price: float | None = None
    discount_rate: float | None = None


class OmnichannelPerformanceRow(BaseModel):
    """Backs GET /sales/omnichannel. Not in the original 10-endpoint list
    (docs/architecture.md), added because it's the only source for the
    physical-vs-e-commerce comparison the Executive Overview and Sales
    Performance dashboard pages require -- fact_retail_sales alone can't
    answer that (it doesn't include the DTC e-commerce channel, which lives
    in fact_ecommerce_orders / mart_omnichannel_performance)."""

    channel_type: str
    sale_date: dt.date
    month_start: dt.date
    units_sold: int
    net_sales: float
    distinct_products_sold: int
    distinct_retailers: int
