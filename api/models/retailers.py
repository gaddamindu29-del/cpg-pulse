from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class RetailerPerformanceOut(BaseModel):
    retailer_id: str
    retailer_name: str
    retailer_type: str
    total_units_sold: int
    total_gross_sales: float
    total_net_sales: float
    net_to_gross_ratio: float | None = None
    distinct_products_sold: int
    distinct_stores: int
    first_sale_date: dt.date | None = None
    last_sale_date: dt.date | None = None
    high_stockout_risk_snapshots: int
    total_inventory_snapshots: int
    high_stockout_risk_rate: float | None = None
    excess_inventory_snapshots: int
    promotion_count: int
    total_marketing_spend: float
