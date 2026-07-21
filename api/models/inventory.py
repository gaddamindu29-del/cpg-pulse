from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class StockoutRiskOut(BaseModel):
    retailer_id: str
    store_id: str
    product_id: str
    snapshot_date: dt.date
    on_hand_units: int
    available_units: int
    avg_daily_units_sold: float | None = None
    velocity_trend: str | None = None
    days_of_supply: float | None = None
    stockout_risk_level: str


class ExcessInventoryRiskOut(BaseModel):
    retailer_id: str
    store_id: str
    product_id: str
    snapshot_date: dt.date
    on_hand_units: int
    available_units: int
    avg_daily_units_sold: float | None = None
    velocity_trend: str | None = None
    days_of_supply: float | None = None
    is_excess_inventory: bool
    excess_inventory_risk_level: str
