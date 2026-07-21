from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ProductOut(BaseModel):
    product_id: str
    upc: str | None = None
    brand: str
    category: str
    subcategory: str
    product_name: str
    flavor: str | None = None
    package_size: str | None = None
    case_quantity: int | None = None
    unit_cost: float
    launch_date: dt.date | None = None
    discontinued_date: dt.date | None = None
    is_discontinued: bool


class ProductPerformanceOut(BaseModel):
    product_id: str
    brand: str
    category: str
    subcategory: str
    unit_cost: float
    is_discontinued: bool
    total_units_sold_all_channels: int
    total_net_sales_all_channels: float
    distinct_retailers_carrying: int
    distinct_stores_selling: int
    first_sale_date: dt.date | None = None
    last_sale_date: dt.date | None = None
    high_stockout_risk_snapshots: int
    total_inventory_snapshots: int
    high_stockout_risk_rate: float | None = None
    excess_inventory_snapshots: int
    promotion_count: int
