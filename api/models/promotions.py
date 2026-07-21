from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class PromotionPerformanceOut(BaseModel):
    promotion_id: str
    retailer_id: str
    product_id: str
    promotion_type: str
    display_type: str | None = None
    start_date: dt.date
    end_date: dt.date
    duration_days: int
    regular_price: float
    promotional_price: float
    discount_percentage: float
    marketing_spend: float
    baseline_days: int | None = None
    baseline_avg_daily_units: float | None = None
    expected_baseline_units: float
    actual_promo_units: int
    actual_promo_net_sales: float
    incremental_units: float
    incremental_revenue: float
    discount_cost: float
    lift_percentage: float | None = None
    promotion_roi: float | None = None
