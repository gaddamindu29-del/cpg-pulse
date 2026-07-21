from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query

from ..models.sales import OmnichannelPerformanceRow, SalesGroupBy, SalesSummaryRow
from ..services import sales_service

router = APIRouter(tags=["sales"])


@router.get("/sales/summary", response_model=list[SalesSummaryRow])
def sales_summary(
    group_by: SalesGroupBy = Query(SalesGroupBy.retailer),
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
    retailer_id: str | None = Query(None),
    category: str | None = Query(None),
) -> list[SalesSummaryRow]:
    """Aggregated retail POS sales, grouped by retailer/product/category/brand/channel.

    Example: GET /sales/summary?group_by=category&start_date=2025-01-01&end_date=2025-01-31
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")

    rows = sales_service.sales_summary(group_by.value, start_date, end_date, retailer_id, category)
    return [SalesSummaryRow(**r) for r in rows]


@router.get("/sales/omnichannel", response_model=list[OmnichannelPerformanceRow])
def omnichannel_performance(
    start_date: dt.date | None = Query(None),
    end_date: dt.date | None = Query(None),
) -> list[OmnichannelPerformanceRow]:
    """Daily sales by channel type (Physical Retail / Omnichannel / Marketplace /
    E-commerce), combining retail POS and direct-to-consumer e-commerce.

    Example: GET /sales/omnichannel?start_date=2025-01-01&end_date=2025-03-31
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")

    rows = sales_service.omnichannel_performance(start_date, end_date)
    return [OmnichannelPerformanceRow(**r) for r in rows]
