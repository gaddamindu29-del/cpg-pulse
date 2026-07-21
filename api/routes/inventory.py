from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from ..models.common import Page, paginate
from ..models.inventory import ExcessInventoryRiskOut, StockoutRiskOut
from ..services import inventory_service

router = APIRouter(tags=["inventory"])


@router.get("/inventory/stockout-risk", response_model=Page[StockoutRiskOut])
def stockout_risk(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    retailer_id: str | None = Query(None),
    store_id: str | None = Query(None),
    risk_level: str | None = Query(None, pattern="^(HIGH|MEDIUM|LOW|NO_RECENT_DEMAND)$"),
    as_of_date: dt.date | None = Query(None, description="Defaults to the latest available snapshot date"),
) -> Page[StockoutRiskOut]:
    """Stockout risk by product x store, ranked most-urgent first.

    Example: GET /inventory/stockout-risk?risk_level=HIGH&retailer_id=RTL-WMT
    """
    rows, total = inventory_service.list_stockout_risk(page, page_size, retailer_id, store_id, risk_level, as_of_date)
    return paginate([StockoutRiskOut(**r) for r in rows], page, page_size, total)


@router.get("/inventory/excess-risk", response_model=Page[ExcessInventoryRiskOut])
def excess_risk(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    retailer_id: str | None = Query(None),
    store_id: str | None = Query(None),
    risk_level: str | None = Query(None, pattern="^(CRITICAL|EXCESS|NORMAL|NO_RECENT_DEMAND)$"),
    as_of_date: dt.date | None = Query(None, description="Defaults to the latest available snapshot date"),
) -> Page[ExcessInventoryRiskOut]:
    """Excess inventory risk by product x store, ranked highest days-of-supply first.

    Example: GET /inventory/excess-risk?risk_level=CRITICAL
    """
    rows, total = inventory_service.list_excess_risk(page, page_size, retailer_id, store_id, risk_level, as_of_date)
    return paginate([ExcessInventoryRiskOut(**r) for r in rows], page, page_size, total)
